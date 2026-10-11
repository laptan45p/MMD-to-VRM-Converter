$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()
$root = $PSScriptRoot
$script:process = $null
$script:job = $null
$form = New-Object System.Windows.Forms.Form
$form.Text = 'MMD -> VRM 0.x / 0.3.1'
$form.Size = New-Object System.Drawing.Size(820,910)
$form.StartPosition = 'CenterScreen'
$form.Font = New-Object System.Drawing.Font('Yu Gothic UI',10)
$form.MinimumSize = $form.Size

function Field($label,$y,$initial) {
    $l = New-Object System.Windows.Forms.Label
    $l.Text=$label; $l.Location=New-Object System.Drawing.Point(15,$y); $l.Size=New-Object System.Drawing.Size(150,25)
    $form.Controls.Add($l)
    $t = New-Object System.Windows.Forms.TextBox
    $t.Text=$initial; $t.Location=New-Object System.Drawing.Point(170,$y); $t.Size=New-Object System.Drawing.Size(520,26)
    $form.Controls.Add($t)
    return $t
}
function Button($text,$x,$y,$action) {
    $b = New-Object System.Windows.Forms.Button
    $b.Text=$text; $b.Location=New-Object System.Drawing.Point($x,$y); $b.Size=New-Object System.Drawing.Size(90,29)
    $b.Add_Click($action); $form.Controls.Add($b); return $b
}
$blender=Field 'Blender.exe' 20 ''
$inputFile=Field 'PMX / ZIP' 60 ''
$outputFile=Field 'VRM保存先' 100 ''
$title=Field 'モデル名 (任意)' 140 ''
$author=Field 'モデルの作者' 180 ''
$license=Field '利用条件URL' 220 ''
$note=New-Object System.Windows.Forms.Label
$note.Text='先にBlenderで「MMD Tools」をインストールしてください。揺れはボーン名から仮設定します。'
$note.Location=New-Object System.Drawing.Point(15,260);$note.Size=New-Object System.Drawing.Size(765,30)
$form.Controls.Add($note)
$script:springControls=@{}
$names=@{hair='髪';ribbon='リボン・紐';sleeve='袖';skirt='スカート';chest='胸'}
$values=@{hair=@(0.8,0.4,0.04,0.012);ribbon=@(1.1,0.45,0.03,0.008);sleeve=@(1.8,0.55,0.04,0.012);skirt=@(2.3,0.6,0.03,0.014);chest=@(2.5,0.6,0,0.006)}
$header=New-Object System.Windows.Forms.Label
$header.Text='揺れの部位                  硬さ                 減衰                 重力                 半径 (m)'
$header.Location=New-Object System.Drawing.Point(15,292);$header.Size=New-Object System.Drawing.Size(765,25);$form.Controls.Add($header)
$row=0
foreach($category in @('hair','ribbon','sleeve','skirt','chest')){
    $y=320+$row*32
    $enabled=New-Object System.Windows.Forms.CheckBox
    $enabled.Text=$names[$category];$enabled.Checked=$true
    $enabled.Location=New-Object System.Drawing.Point(15,$y);$enabled.Size=New-Object System.Drawing.Size(160,26);$form.Controls.Add($enabled)
    $controls=@{enabled=$enabled};$column=0
    foreach($key in @('stiffness','drag','gravity','radius')){
        $number=New-Object System.Windows.Forms.NumericUpDown
        $number.DecimalPlaces=3;$number.Minimum=0
        $number.Maximum=if($key -eq 'stiffness'){10}elseif($key -eq 'radius'){0.1}else{1}
        $number.Increment=if($key -eq 'radius'){0.001}else{0.05}
        $number.Value=$values[$category][$column]
        $number.Location=New-Object System.Drawing.Point((185+$column*140),$y);$number.Size=New-Object System.Drawing.Size(120,26)
        $form.Controls.Add($number);$controls[$key]=$number;$column++
    }
    $script:springControls[$category]=$controls;$row++
}
$collisions=New-Object System.Windows.Forms.CheckBox
$collisions.Text='髪・衣装の衝突判定を追加（仮設定） / 胸は控えめな初期値'
$collisions.Checked=$true;$collisions.Location=New-Object System.Drawing.Point(15,485);$collisions.Size=New-Object System.Drawing.Size(765,26);$form.Controls.Add($collisions)
function SpringOptions {
    $options=@{colliders=$collisions.Checked}
    foreach($category in @('hair','ribbon','sleeve','skirt','chest')){
        $c=$script:springControls[$category]
        $options[$category]=@{enabled=$c.enabled.Checked;stiffness=[double]$c.stiffness.Value;drag=[double]$c.drag.Value;gravity=[double]$c.gravity.Value;radius=[double]$c.radius.Value}
    }
    return $options
}
$logBox=New-Object System.Windows.Forms.TextBox
$logBox.Multiline=$true;$logBox.ReadOnly=$true;$logBox.ScrollBars='Both';$logBox.WordWrap=$false
$logBox.Location=New-Object System.Drawing.Point(15,565);$logBox.Size=New-Object System.Drawing.Size(765,290)
$logBox.Anchor='Top,Bottom,Left,Right';$form.Controls.Add($logBox)
$status=New-Object System.Windows.Forms.Label
$status.Text='待機中';$status.Location=New-Object System.Drawing.Point(230,525);$status.Size=New-Object System.Drawing.Size(550,30)
$form.Controls.Add($status)
$browseBlender=Button '選択' 700 18 {
    $d=New-Object System.Windows.Forms.OpenFileDialog;$d.Filter='Blender|blender.exe'
    if($d.ShowDialog() -eq 'OK'){$blender.Text=$d.FileName}
}
$browseInput=Button '選択' 700 58 {
    $d=New-Object System.Windows.Forms.OpenFileDialog;$d.Filter='MMDモデル|*.pmx;*.zip'
    if($d.ShowDialog() -eq 'OK'){
        $inputFile.Text=$d.FileName
        $outputFile.Text=[System.IO.Path]::ChangeExtension($d.FileName,'.vrm')
    }
}
$browseOutput=Button '選択' 700 98 {
    $d=New-Object System.Windows.Forms.SaveFileDialog;$d.Filter='VRM|*.vrm';$d.FileName=$outputFile.Text
    if($d.ShowDialog() -eq 'OK'){$outputFile.Text=$d.FileName}
}
$settings=Join-Path $root 'settings.json'
if(Test-Path $settings){
    try{$s=Get-Content -Raw -Encoding UTF8 $settings|ConvertFrom-Json
        $blender.Text=$s.blender;$author.Text=$s.author;$license.Text=$s.license_url
        if($s.spring_options){
            $collisions.Checked=[bool]$s.spring_options.colliders
            foreach($category in @('hair','ribbon','sleeve','skirt','chest')){
                $saved=$s.spring_options.$category
                if($saved){
                    $script:springControls[$category].enabled.Checked=[bool]$saved.enabled
                    foreach($key in @('stiffness','drag','gravity','radius')){
                        $value=[decimal]$saved.$key;$control=$script:springControls[$category][$key]
                        if($value -ge $control.Minimum -and $value -le $control.Maximum){$control.Value=$value}
                    }
                }
            }
        }
    }catch{}
}
if(-not $blender.Text){
    $base=Join-Path $env:ProgramFiles 'Blender Foundation'
    if(Test-Path $base){
        $found=Get-ChildItem $base -Filter blender.exe -Recurse -ErrorAction SilentlyContinue|Sort-Object FullName -Descending|Select-Object -First 1
        if($found){$blender.Text=$found.FullName}
    }
}
$timer=New-Object System.Windows.Forms.Timer;$timer.Interval=600
$timer.Add_Tick({
    if(-not $script:process){return}
    $log=Join-Path $script:job 'conversion.log'
    if(Test-Path $log){
        try{
            $text=[System.IO.File]::ReadAllText($log,[System.Text.Encoding]::UTF8)
            if($logBox.Text -ne $text){$logBox.Text=$text;$logBox.SelectionStart=$logBox.Text.Length;$logBox.ScrollToCaret()}
        }catch{}
    }
    if($script:process.HasExited){
        $timer.Stop()
        if(($script:process.ExitCode -eq 0) -and (Test-Path (Join-Path $script:job 'success.json'))){
            $status.Text='完了。VRM対応ソフトで動作を確認してください。'
        }else{
            $status.Text='変換失敗。ログを確認してください。'
            if(-not (Test-Path $log)){$logBox.AppendText("`r`nBlenderが起動できませんでした。Blender.exeの場所を確認してください。")}
        }
        $script:process.Dispose();$script:process=$null;$runButton.Enabled=$true;$stopButton.Enabled=$false
    }
})
$runButton=Button '変換開始' 15 520 {
    try{
        if(-not(Test-Path -LiteralPath $blender.Text -PathType Leaf)){throw 'Blender.exeを指定してください。'}
        if([System.IO.Path]::GetFileName($blender.Text) -ne 'blender.exe'){throw 'blender.exeを選んでください。'}
        if(-not(Test-Path -LiteralPath $inputFile.Text -PathType Leaf)){throw 'PMXまたはZIPを指定してください。'}
        if(-not $author.Text.Trim()){throw '元モデルの作者名を入力してください。'}
        if(-not $outputFile.Text.Trim()){throw '保存先を指定してください。'}
        $out=[System.IO.Path]::GetFullPath($outputFile.Text)
        if([System.IO.Path]::GetExtension($out) -ne '.vrm'){throw '保存先の拡張子は.vrmにしてください。'}
        if(-not(Test-Path ([System.IO.Path]::GetDirectoryName($out)))){throw '保存先フォルダがありません。'}
        if(Test-Path -LiteralPath $out){
            if([System.Windows.Forms.MessageBox]::Show('既存のVRMを上書きしますか？','上書き','YesNo') -ne 'Yes'){return}
        }
        $script:job=Join-Path (Join-Path $root 'logs') ([DateTime]::Now.ToString('yyyyMMdd-HHmmss')+'-'+[Guid]::NewGuid().ToString('N').Substring(0,6))
        New-Item -ItemType Directory -Path $script:job -Force|Out-Null
        $cfg=@{input=$inputFile.Text;output=$out;work=$script:job;log=(Join-Path $script:job 'conversion.log');title=$title.Text;author=$author.Text;license_url=$license.Text;spring_options=(SpringOptions)}
        $cfgPath=Join-Path $script:job 'config.json'
        [System.IO.File]::WriteAllText($cfgPath,($cfg|ConvertTo-Json -Depth 8),[System.Text.UTF8Encoding]::new($false))
        [System.IO.File]::WriteAllText($settings,(@{blender=$blender.Text;author=$author.Text;license_url=$license.Text;spring_options=(SpringOptions)}|ConvertTo-Json -Depth 8),[System.Text.UTF8Encoding]::new($false))
        $worker=Join-Path $root 'convert.py'
        $pi=New-Object System.Diagnostics.ProcessStartInfo
        $pi.FileName=$blender.Text
        $pi.Arguments='--background --python-exit-code 1 --python "'+$worker+'" -- "'+$cfgPath+'"'
        $pi.WorkingDirectory=$root;$pi.UseShellExecute=$false;$pi.CreateNoWindow=$true
        $pi.EnvironmentVariables['PYTHONIOENCODING']='utf-8'
        $script:process=New-Object System.Diagnostics.Process;$script:process.StartInfo=$pi
        if(-not $script:process.Start()){throw 'Blenderを起動できませんでした。'}
        $logBox.Text='起動中...';$status.Text='変換中';$runButton.Enabled=$false;$stopButton.Enabled=$true;$timer.Start()
    }catch{
        $status.Text='開始できませんでした'
        [System.Windows.Forms.MessageBox]::Show($_.Exception.Message,'エラー')|Out-Null
    }
}
$stopButton=Button '停止' 115 520 {
    if($script:process -and -not $script:process.HasExited){
        $script:process.Kill();$status.Text='停止しています'
    }
}
$stopButton.Enabled=$false
$form.Add_FormClosing({
    if($script:process -and -not $script:process.HasExited){
        if([System.Windows.Forms.MessageBox]::Show('変換を停止して閉じますか？','確認','YesNo') -ne 'Yes'){$_.Cancel=$true;return}
        $script:process.Kill()
    }
    $timer.Stop()
})
[void]$form.ShowDialog()
