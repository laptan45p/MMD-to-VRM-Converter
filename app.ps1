$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()
$root = $PSScriptRoot
$script:process = $null
$script:job = $null
$form = New-Object System.Windows.Forms.Form
$form.Text = 'MMD -> VRM 0.x / 0.2.1 修正版'
$form.Size = New-Object System.Drawing.Size(820,710)
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
$note.Text='先にBlenderで「MMD Tools」をインストールしてください。物理は未対応です。'
$note.Location=New-Object System.Drawing.Point(15,260);$note.Size=New-Object System.Drawing.Size(765,30)
$form.Controls.Add($note)
$logBox=New-Object System.Windows.Forms.TextBox
$logBox.Multiline=$true;$logBox.ReadOnly=$true;$logBox.ScrollBars='Both';$logBox.WordWrap=$false
$logBox.Location=New-Object System.Drawing.Point(15,350);$logBox.Size=New-Object System.Drawing.Size(765,300)
$logBox.Anchor='Top,Bottom,Left,Right';$form.Controls.Add($logBox)
$status=New-Object System.Windows.Forms.Label
$status.Text='待機中';$status.Location=New-Object System.Drawing.Point(230,305);$status.Size=New-Object System.Drawing.Size(550,30)
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
$runButton=Button '変換開始' 15 300 {
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
        $cfg=@{input=$inputFile.Text;output=$out;work=$script:job;log=(Join-Path $script:job 'conversion.log');title=$title.Text;author=$author.Text;license_url=$license.Text}
        $cfgPath=Join-Path $script:job 'config.json'
        [System.IO.File]::WriteAllText($cfgPath,($cfg|ConvertTo-Json),[System.Text.UTF8Encoding]::new($false))
        [System.IO.File]::WriteAllText($settings,(@{blender=$blender.Text;author=$author.Text;license_url=$license.Text}|ConvertTo-Json),[System.Text.UTF8Encoding]::new($false))
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
$stopButton=Button '停止' 115 300 {
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
