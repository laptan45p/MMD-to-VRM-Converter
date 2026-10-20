$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()
$root = $PSScriptRoot
$script:process = $null
$script:job = $null
$form = New-Object System.Windows.Forms.Form
$form.Text = 'MMD -> VRM 0.x / 0.5.0'
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
$modeLabel=New-Object System.Windows.Forms.Label
$modeLabel.Text='変換モード';$modeLabel.Location=New-Object System.Drawing.Point(15,260);$modeLabel.Size=New-Object System.Drawing.Size(150,25);$form.Controls.Add($modeLabel)
$mode=New-Object System.Windows.Forms.ComboBox
$mode.DropDownStyle='DropDownList';$mode.Location=New-Object System.Drawing.Point(170,258);$mode.Size=New-Object System.Drawing.Size(310,26)
[void]$mode.Items.Add('通常変換（服付き）');[void]$mode.Items.Add('素体のみ（実験機能）');$mode.SelectedIndex=0;$form.Controls.Add($mode)
$bodyTemplate=Field '補完用VRM 0.x' 300 ''
$bodyMesh=Field '体メッシュ名 (任意)' 340 ''
$bodyHint=New-Object System.Windows.Forms.Label
$bodyHint.Text='空欄は体メッシュを自動選択。首・肌色は要調整。MMD Toolsが必要です。'
$bodyHint.Location=New-Object System.Drawing.Point(15,410);$bodyHint.Size=New-Object System.Drawing.Size(765,25);$form.Controls.Add($bodyHint)
$neckLabel=New-Object System.Windows.Forms.Label
$neckLabel.Text='首の境界補正 (m)';$neckLabel.Location=New-Object System.Drawing.Point(15,380);$neckLabel.Size=New-Object System.Drawing.Size(150,25);$form.Controls.Add($neckLabel)
$neckOffset=New-Object System.Windows.Forms.NumericUpDown
$neckOffset.DecimalPlaces=3;$neckOffset.Minimum=-0.1;$neckOffset.Maximum=0.1;$neckOffset.Increment=0.005
$neckOffset.Location=New-Object System.Drawing.Point(170,378);$neckOffset.Size=New-Object System.Drawing.Size(120,26);$form.Controls.Add($neckOffset)
$widthLabel=New-Object System.Windows.Forms.Label
$widthLabel.Text='体の幅・厚み倍率';$widthLabel.Location=New-Object System.Drawing.Point(330,380);$widthLabel.Size=New-Object System.Drawing.Size(160,25);$form.Controls.Add($widthLabel)
$bodyWidth=New-Object System.Windows.Forms.NumericUpDown
$bodyWidth.DecimalPlaces=2;$bodyWidth.Minimum=0.5;$bodyWidth.Maximum=1.5;$bodyWidth.Increment=0.05;$bodyWidth.Value=1
$bodyWidth.Location=New-Object System.Drawing.Point(500,378);$bodyWidth.Size=New-Object System.Drawing.Size(120,26);$form.Controls.Add($bodyWidth)
$browseTemplate=Button '選択' 700 298 {
    $d=New-Object System.Windows.Forms.OpenFileDialog;$d.Filter='補完用VRM|*.vrm'
    if($d.ShowDialog() -eq 'OK'){$bodyTemplate.Text=$d.FileName}
}
$appearance=New-Object System.Windows.Forms.Form
$appearance.Text='体型・肌色の調整（素体モード）';$appearance.Size=New-Object System.Drawing.Size(640,590)
$appearance.StartPosition='CenterParent';$appearance.FormBorderStyle='FixedDialog';$appearance.MaximizeBox=$false;$appearance.MinimizeBox=$false;$appearance.ShowInTaskbar=$false
$appearance.Font=$form.Font
$script:bodyShapes=@{}
$shapeNames=@{bust='胸のボリューム';waist='ウエスト';hips='腰・お尻';thighs='太もも';upper_arms='二の腕';neck='首の太さ'}
$row=0
foreach($key in @('bust','waist','hips','thighs','upper_arms','neck')){
    $label=New-Object System.Windows.Forms.Label
    $label.Text=$shapeNames[$key]+'（1.0が基準）';$label.Location=New-Object System.Drawing.Point(15,(20+$row*33));$label.Size=New-Object System.Drawing.Size(340,26);$appearance.Controls.Add($label)
    $number=New-Object System.Windows.Forms.NumericUpDown
    $number.DecimalPlaces=2;$number.Minimum=0.5;$number.Maximum=1.5;$number.Increment=0.05;$number.Value=1
    $number.Location=New-Object System.Drawing.Point(410,(18+$row*33));$number.Size=New-Object System.Drawing.Size(120,26)
    $appearance.Controls.Add($number);$script:bodyShapes[$key]=$number;$row++
}
$skinMatch=New-Object System.Windows.Forms.CheckBox
$skinMatch.Text='元MMDの肌色に自動補正する';$skinMatch.Checked=$true;$skinMatch.Location=New-Object System.Drawing.Point(15,230);$skinMatch.Size=New-Object System.Drawing.Size(560,26);$appearance.Controls.Add($skinMatch)
$skinLabel=New-Object System.Windows.Forms.Label
$skinLabel.Text='肌色補正の強さ（0〜1）';$skinLabel.Location=New-Object System.Drawing.Point(15,270);$skinLabel.Size=New-Object System.Drawing.Size(330,26);$appearance.Controls.Add($skinLabel)
$skinStrength=New-Object System.Windows.Forms.NumericUpDown
$skinStrength.DecimalPlaces=2;$skinStrength.Minimum=0;$skinStrength.Maximum=1;$skinStrength.Increment=0.05;$skinStrength.Value=0.8
$skinStrength.Location=New-Object System.Drawing.Point(410,268);$skinStrength.Size=New-Object System.Drawing.Size(120,26);$appearance.Controls.Add($skinStrength)
$sourceSkinLabel=New-Object System.Windows.Forms.Label
$sourceSkinLabel.Text='元MMDの肌材質名';$sourceSkinLabel.Location=New-Object System.Drawing.Point(15,310);$sourceSkinLabel.Size=New-Object System.Drawing.Size(180,26);$appearance.Controls.Add($sourceSkinLabel)
$sourceSkin=New-Object System.Windows.Forms.TextBox
$sourceSkin.Location=New-Object System.Drawing.Point(200,308);$sourceSkin.Size=New-Object System.Drawing.Size(390,26);$appearance.Controls.Add($sourceSkin)
$templateSkinLabel=New-Object System.Windows.Forms.Label
$templateSkinLabel.Text='補完VRMの肌材質名';$templateSkinLabel.Location=New-Object System.Drawing.Point(15,350);$templateSkinLabel.Size=New-Object System.Drawing.Size(180,26);$appearance.Controls.Add($templateSkinLabel)
$templateSkin=New-Object System.Windows.Forms.TextBox
$templateSkin.Location=New-Object System.Drawing.Point(200,348);$templateSkin.Size=New-Object System.Drawing.Size(390,26);$appearance.Controls.Add($templateSkin)
$appearanceHint=New-Object System.Windows.Forms.Label
$appearanceHint.Text='材質名は空欄で自動判定。肌・顔の色を基準にします。自動判定できない場合はログの材質名を指定してください。体型は骨格に合わせた素体からの調整で、服の下の体型を推定する機能ではありません。変更後は再変換が必要です。'
$appearanceHint.Location=New-Object System.Drawing.Point(15,392);$appearanceHint.Size=New-Object System.Drawing.Size(580,95);$appearance.Controls.Add($appearanceHint)
$skinMatch.Add_CheckedChanged({$skinStrength.Enabled=$skinMatch.Checked;$sourceSkin.Enabled=$skinMatch.Checked;$templateSkin.Enabled=$skinMatch.Checked})
$resetAppearance=New-Object System.Windows.Forms.Button
$resetAppearance.Text='初期値に戻す';$resetAppearance.Location=New-Object System.Drawing.Point(15,505);$resetAppearance.Size=New-Object System.Drawing.Size(140,30)
$resetAppearance.Add_Click({foreach($control in $script:bodyShapes.Values){$control.Value=1};$skinMatch.Checked=$true;$skinStrength.Value=0.8;$sourceSkin.Text='';$templateSkin.Text=''})
$appearance.Controls.Add($resetAppearance)
$closeAppearance=New-Object System.Windows.Forms.Button
$closeAppearance.Text='閉じる';$closeAppearance.Location=New-Object System.Drawing.Point(480,505);$closeAppearance.Size=New-Object System.Drawing.Size(110,30)
$closeAppearance.Add_Click({$appearance.Hide()});$appearance.Controls.Add($closeAppearance)
$appearanceButton=Button '体型・肌色' 500 258 {[void]$appearance.ShowDialog($form)}
$mode.Add_SelectedIndexChanged({
    $on=($mode.SelectedIndex -eq 1)
    $bodyTemplate.Enabled=$on;$bodyMesh.Enabled=$on;$neckOffset.Enabled=$on;$bodyWidth.Enabled=$on;$browseTemplate.Enabled=$on;$appearanceButton.Enabled=$on
})
$bodyTemplate.Enabled=$false;$bodyMesh.Enabled=$false;$neckOffset.Enabled=$false;$bodyWidth.Enabled=$false;$browseTemplate.Enabled=$false;$appearanceButton.Enabled=$false
function BodyOptions {
    $shapes=@{}
    foreach($key in $script:bodyShapes.Keys){$shapes[$key]=[double]$script:bodyShapes[$key].Value}
    return @{mesh_name=$bodyMesh.Text;neck_offset=[double]$neckOffset.Value;width=[double]$bodyWidth.Value;shape=$shapes;skin_match=$skinMatch.Checked;skin_strength=[double]$skinStrength.Value;source_skin_material=$sourceSkin.Text;template_skin_material=$templateSkin.Text}
}
$script:springControls=@{}
$names=@{hair='髪';ribbon='リボン・紐';sleeve='袖';skirt='スカート';chest='胸'}
$values=@{hair=@(0.8,0.4,0.04,0.012);ribbon=@(1.1,0.45,0.03,0.008);sleeve=@(1.8,0.55,0.04,0.012);skirt=@(2.3,0.6,0.03,0.014);chest=@(2.5,0.6,0,0.006)}
$header=New-Object System.Windows.Forms.Label
$header.Text='揺れの部位                  硬さ                 減衰                 重力                 半径 (m)'
$header.Location=New-Object System.Drawing.Point(15,440);$header.Size=New-Object System.Drawing.Size(765,25);$form.Controls.Add($header)
$row=0
foreach($category in @('hair','ribbon','sleeve','skirt','chest')){
    $y=468+$row*32
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
$collisions.Checked=$true;$collisions.Location=New-Object System.Drawing.Point(15,633);$collisions.Size=New-Object System.Drawing.Size(765,26);$form.Controls.Add($collisions)
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
$logBox.Location=New-Object System.Drawing.Point(15,720);$logBox.Size=New-Object System.Drawing.Size(765,135)
$logBox.Anchor='Top,Bottom,Left,Right';$form.Controls.Add($logBox)
$status=New-Object System.Windows.Forms.Label
$status.Text='待機中';$status.Location=New-Object System.Drawing.Point(230,677);$status.Size=New-Object System.Drawing.Size(550,30)
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
        if($s.body_template){$bodyTemplate.Text=$s.body_template}
        if($s.body_options){
            $bodyMesh.Text=$s.body_options.mesh_name
            if($s.body_options.shape){
                foreach($key in $script:bodyShapes.Keys){
                    $v=[decimal]$s.body_options.shape.$key
                    if($v -ge 0.5 -and $v -le 1.5){$script:bodyShapes[$key].Value=$v}
                }
            }
            if($s.body_options.PSObject.Properties.Name -contains 'skin_match'){$skinMatch.Checked=[bool]$s.body_options.skin_match}
            if($s.body_options.PSObject.Properties.Name -contains 'skin_strength'){
                $v=[decimal]$s.body_options.skin_strength
                if($v -ge 0 -and $v -le 1){$skinStrength.Value=$v}
            }
            $sourceSkin.Text=$s.body_options.source_skin_material;$templateSkin.Text=$s.body_options.template_skin_material
            $v=[decimal]$s.body_options.neck_offset
            if($v -ge -0.1 -and $v -le 0.1){$neckOffset.Value=$v}
            $v=[decimal]$s.body_options.width
            if($v -ge 0.5 -and $v -le 1.5){$bodyWidth.Value=$v}
        }
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
$runButton=Button '変換開始' 15 672 {
    try{
        if(-not(Test-Path -LiteralPath $blender.Text -PathType Leaf)){throw 'Blender.exeを指定してください。'}
        if([System.IO.Path]::GetFileName($blender.Text) -ne 'blender.exe'){throw 'blender.exeを選んでください。'}
        if(-not(Test-Path -LiteralPath $inputFile.Text -PathType Leaf)){throw 'PMXまたはZIPを指定してください。'}
        if($mode.SelectedIndex -eq 1 -and -not(Test-Path -LiteralPath $bodyTemplate.Text -PathType Leaf)){throw '補完用VRMを選んでください。'}
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
        $cfg=@{input=$inputFile.Text;output=$out;work=$script:job;log=(Join-Path $script:job 'conversion.log');title=$title.Text;author=$author.Text;license_url=$license.Text;spring_options=(SpringOptions);body_template=$bodyTemplate.Text;body_options=(BodyOptions)}
        $cfg.conversion_mode=if($mode.SelectedIndex -eq 1){'body_only'}else{'normal'}
        $cfgPath=Join-Path $script:job 'config.json'
        [System.IO.File]::WriteAllText($cfgPath,($cfg|ConvertTo-Json -Depth 8),[System.Text.UTF8Encoding]::new($false))
        [System.IO.File]::WriteAllText($settings,(@{blender=$blender.Text;author=$author.Text;license_url=$license.Text;spring_options=(SpringOptions);body_template=$bodyTemplate.Text;body_options=(BodyOptions)}|ConvertTo-Json -Depth 8),[System.Text.UTF8Encoding]::new($false))
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
$stopButton=Button '停止' 115 672 {
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
