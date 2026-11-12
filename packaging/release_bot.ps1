# Reliz boti: yig'ish natijasini (out2) to'liq sinaydi va FAQAT hamma sinov o'tsa D:\...\UzLungCT_dastur 02.11.2026 ga joylaydi.
# Sinovlar: 1) buzilgan qism aniqlanishi, 2) yetishmayotgan qism aniqlanishi, 3) toza o'rnatish (boshqa papka, port 8031), 4) izolyatsiya,
# 5) 23 avtomatik test, 6) qayta o'rnatish (yangilash) ma'lumotni saqlashi. Jurnal: C:\ZG\build_exe\release_log.txt
$ErrorActionPreference='Continue'; $L='C:\ZG\build_exe\release_log.txt'; function W($s){ "$(Get-Date -f 'HH:mm:ss') $s" | Tee-Object -FilePath $L -Append }
$O='C:\ZG\build_exe\out2'; $X='C:\ZG\exe_test\rel'; $TR="$X\transfer"
if (Test-Path $X) { foreach($d in "$X\inst","$X\inst_bad","$X\inst_miss"){ if(Test-Path "$d\python\python.exe"){ Push-Location $d; & "$d\python\python.exe" -E -s -m uzlungct.autostart stop *> $null; Pop-Location } }; Remove-Item $X -Recurse -Force }
New-Item -ItemType Directory -Force $TR | Out-Null; Copy-Item "$O\*" $TR; W "ko'chirildi: $((gci $TR).Count) fayl"
function Inst($dir,$port,$src){ & "$src\UzLungMSKT.exe" --dir $dir --port $port --no-autostart --no-shortcut --no-browser --quiet *> "$dir.out.txt"; return $LASTEXITCODE }
# 1) buzilgan qism
$B="$X\bad"; New-Item -ItemType Directory -Force $B | Out-Null; Copy-Item "$TR\UzLungMSKT.exe","$TR\UzLungMSKT_parts.json" $B; gci "$TR\*.zip" | % { New-Item -ItemType HardLink -Path "$B\$($_.Name)" -Target $_.FullName | Out-Null }
Remove-Item "$B\UzLungMSKT_data_03.zip"; Copy-Item "$TR\UzLungMSKT_data_03.zip" "$B\UzLungMSKT_data_03.zip"
$fs=[IO.File]::Open("$B\UzLungMSKT_data_03.zip",'Open','ReadWrite'); $fs.Seek(500000000,'Begin')|Out-Null; $byt=$fs.ReadByte(); $fs.Seek(-1,'Current')|Out-Null; $fs.WriteByte([byte]($byt -bxor 0xFF)); $fs.Close()
$rc=Inst "$X\inst_bad" 8039 $B; $msg=(Get-Content "$X\inst_bad\install.log" | Select-String 'XATO').Line
if ($rc -eq 1 -and $msg -match 'buzilgan') { W "OK 1: buzilgan qism aniqlandi: $msg" } else { W "ALERT 1: buzilish aniqlanmadi (kod $rc)"; exit 1 }
if (Test-Path "$X\inst_bad\python") { W "ALERT 1b: buzilgan paketdan fayl ochilgan"; exit 1 }
# 2) yetishmayotgan qism
Remove-Item "$B\UzLungMSKT_data_03.zip"; New-Item -ItemType HardLink -Path "$B\UzLungMSKT_data_03.zip" -Target "$TR\UzLungMSKT_data_03.zip" | Out-Null; Remove-Item "$B\UzLungMSKT_data_04.zip"; $rc=Inst "$X\inst_miss" 8038 $B; $msg=(Get-Content "$X\inst_miss\install.log" | Select-String 'XATO').Line
if ($rc -eq 1 -and $msg -match 'topilmadi') { W "OK 2: yetishmayotgan qism aniqlandi" } else { W "ALERT 2 (kod $rc)"; exit 1 }
Remove-Item $B -Recurse -Force
# 3) toza o'rnatish
$t=Measure-Command { $rc=Inst "$X\inst" 8031 $TR }; if ($rc -ne 0) { W "ALERT 3: o'rnatish kodi $rc"; exit 1 }; W ("OK 3: toza o'rnatish {0:N0} s" -f $t.TotalSeconds)
# 4) izolyatsiya
Copy-Item C:\ZG\build_exe\isolation_check.py "$X\inst\_iso.py"; Push-Location "$X\inst"; & "$X\inst\python\python.exe" -E -s "$X\inst\_iso.py" *> "$X\iso.txt"; $rc=$LASTEXITCODE; Pop-Location; Remove-Item "$X\inst\_iso.py"
if ($rc -ne 0) { W "ALERT 4: izolyatsiya"; exit 1 }; W ("OK 4: " + (Select-String "$X\iso.txt" -Pattern 'TASHQI').Line)
# 8) regressiya: zaharlangan foydalanuvchi paketlari + .zip nomli 7z arxiv + to'liq SenGuard-3D
$ct="C:\ZG\build_exe\regress_ct.nii.gz"
Push-Location "$X\inst"; & "$X\inst\python\python.exe" -E -s C:\ZG\build_exe\regress_check.py $ct "$X\regr" *> "$X\regr.txt"; $rc=$LASTEXITCODE; Pop-Location
if ($rc -ne 0) { W "ALERT 8: regressiya ($((Get-Content "$X\regr.txt" | Select -Last 2) -join ' | '))"; exit 1 }; W ("OK 8: " + ((Get-Content "$X\regr.txt" | Select-String 'OK').Line -join '; '))
# 5) avtomatik testlar
(Get-Content C:\ZG\platform_test\p_setup.py -Raw).Replace('http://127.0.0.1:8010','http://127.0.0.1:8031').Replace('C:\ZG\platform_test\workspace',"$X\inst\workspace").Replace('C:\ZG\platform_test\test_seed.json',"$X\seed.json") | Set-Content "$X\setup.py" -Encoding utf8
& C:\ZS\venv\Scripts\python.exe "$X\setup.py" *> "$X\setup.txt"
Push-Location C:\ZG\platform_tests; $env:PYTHONPATH='C:\ZG\platform_tests\_lib;C:\ZG\platform_tests'; $env:UZ_BASE='http://127.0.0.1:8031'; $env:UZ_SEED="$X\seed.json"; $env:UZ_JOBS="$X\inst\workspace\jobs"
& C:\ZS\venv\Scripts\python.exe -m pytest -rfE *> "$X\tests.txt"; $rc=$LASTEXITCODE; Pop-Location
$sum=(Get-Content "$X\tests.txt" | Select-Object -Last 1); if ($rc -ne 0) { W "ALERT 5: testlar $sum"; exit 1 }; W "OK 5: $sum"
# 6) yangilash
$rc=Inst "$X\inst" 8031 $TR; & C:\ZS\venv\Scripts\python.exe C:\ZG\build_exe\update_check.py http://127.0.0.1:8031 "$X\seed.json" *> "$X\upd.txt"; $u=$LASTEXITCODE
if ($rc -ne 0 -or $u -ne 0) { W "ALERT 6: yangilash"; exit 1 }; W "OK 6: yangilash ma'lumotni saqladi"
Push-Location "$X\inst"; & "$X\inst\python\python.exe" -E -s -m uzlungct.autostart stop *> $null; Pop-Location
# 9) avtostart + ish stoli yorlig'i (kompyuter o'chib-yonishini taqlid qilish). Sinovdan keyin yaratilgan yozuvlar o'chiriladi.
$RK='HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'; $SL=Join-Path ([Environment]::GetFolderPath('Startup')) 'UzLungMSKT_server.lnk'; $DL=Join-Path ([Environment]::GetFolderPath('DesktopDirectory')) 'UzLungMSKT.lnk'
function Up9($s){ $t=Get-Date; while(((Get-Date)-$t).TotalSeconds -lt $s){ try{ if((Invoke-WebRequest 'http://127.0.0.1:8031/' -UseBasicParsing -TimeoutSec 3).Content -match 'UzLung'){ return $true } }catch{}; Start-Sleep 2 }; return $false }
function Stop9(){ Push-Location "$X\inst"; & "$X\inst\python\python.exe" -E -s -m uzlungct.autostart stop *> $null; Pop-Location; Start-Sleep 3 }
function Clean9(){ Stop9; Remove-ItemProperty $RK -Name UzLungMSKT -ErrorAction SilentlyContinue; Remove-Item $SL,$DL -ErrorAction SilentlyContinue }
& "$TR\UzLungMSKT.exe" --dir "$X\inst" --port 8031 --no-browser --quiet *> "$X\inst9.out.txt"; $rc=$LASTEXITCODE
$sh=New-Object -ComObject WScript.Shell; $run=(Get-ItemProperty $RK -ErrorAction SilentlyContinue).UzLungMSKT
$ok9 = ($rc -eq 0) -and ($run -like "*$X\inst\*UzLungCT_server.pyw*") -and (Test-Path $SL) -and (Test-Path $DL) -and ($sh.CreateShortcut($DL).Arguments -like '*UzLungMSKT_ochish.pyw*')
if (-not $ok9) { W "ALERT 9a: yozuvlar yaratilmadi (kod $rc, run=$run)"; Clean9; exit 1 }
Stop9; Start-Process cmd -ArgumentList ('/c start "" ' + $run) -WindowStyle Hidden; if (-not (Up9 300)) { W "ALERT 9b: reyestr avtostarti serverni yoqmadi"; Clean9; exit 1 }
Stop9; Start-Process $SL; if (-not (Up9 300)) { W "ALERT 9c: Startup yorlig'i serverni yoqmadi"; Clean9; exit 1 }
Stop9; $ol="$X\inst\workspace\logs\ochish.log"; Remove-Item $ol -ErrorAction SilentlyContinue; Start-Process $DL
if (-not (Up9 330)) { W "ALERT 9d: ish stoli yorlig'i (server o'chiq) serverni yoqmadi"; Clean9; exit 1 }; Start-Sleep 5
Start-Process $DL; Start-Sleep 15; $lg=Get-Content $ol -Raw -ErrorAction SilentlyContinue
if ($lg -notmatch 'server ishga tushdi' -or $lg -notmatch 'server ishlayapti -> brauzer') { W "ALERT 9e: ochish.log: $lg"; Clean9; exit 1 }
Clean9; W "OK 9: reyestr avtostarti, Startup yorlig'i, ish stoli yorlig'i (server o'chiq va yoniq holatda) ishladi"
# 7) joylash (eski fayllar "eski" papkasiga ko'chiriladi)
$D=(gci 'D:\' -Directory | ? Name -like 'O*' | select -First 1).FullName + '\UzLungCT_dastur 02.11.2026'
$E="$D\eski_$(Get-Date -f 'HHmm')"; New-Item -ItemType Directory -Force $E | Out-Null; gci $D -File | % { Move-Item $_.FullName $E }
Copy-Item "$TR\*" $D; foreach ($f in gci $TR) { if ((Get-FileHash $f.FullName).Hash -ne (Get-FileHash "$D\$($f.Name)").Hash) { W "ALERT 7: nusxa mos emas $($f.Name)"; exit 1 } }
W "OK 7: joylandi $D (eski fayllar: $E)"; W "RELIZ TAYYOR"
