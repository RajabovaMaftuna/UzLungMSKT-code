# 33-promt: toza xona o'rnatish sinovi. Jurnal: C:\ZG\build_exe\toza_sinov_log.txt
$ErrorActionPreference='Continue'; $L='C:\ZG\build_exe\toza_sinov_log.txt'; Remove-Item $L -ErrorAction SilentlyContinue
function W($s){ "$(Get-Date -f 'HH:mm:ss') $s" | Tee-Object -FilePath $L -Append }
$D=(gci 'D:\' -Directory | ? Name -like 'O*' | select -First 1).FullName + '\UzLungCT_dastur 02.11.2026'
$X='C:\ZG\toza_sinov'; $TR="$X\transfer"; $I='C:\ZG\toza_sinov\inst'; $P=8050
if (Test-Path $I) { W "TO'XTADI: $I bo'sh emas"; exit 1 }
New-Item -ItemType Directory -Force $TR | Out-Null
gci $D -File | ? Name -like 'UzLungMSKT*' | ? Name -ne 'UzLungMSKT_hisobot.md' | % { Copy-Item $_.FullName $TR }
# T1
$m = Get-Content "$TR\UzLungMSKT_parts.json" -Raw | ConvertFrom-Json; $bad = @($m.qismlar | ? { (Get-FileHash "$TR\$($_.fayl)").Hash.ToLower() -ne $_.sha256 })
if ($bad.Count) { W "XATO T1: sha256 mos emas"; exit 1 }; W "OK T1: $($m.qismlar.Count) qism sha256 mos; $($m.versiya)"
# T2
$t = Measure-Command { & "$TR\UzLungMSKT.exe" --dir $I --port $P --no-autostart --no-shortcut --no-browser --quiet *> "$X\install_out.txt" }; $rc=$LASTEXITCODE
$code = Test-Path "$I\workspace\BOSHLANGICH_ADMIN_KODI.txt"
if ($rc -ne 0 -or -not $code) { W "XATO T2: kod $rc, kirish kodi fayli $code"; exit 1 }; W ("OK T2: noldan o'rnatish {0:N0} s, birinchi kirish kodi fayli yaratildi" -f $t.TotalSeconds)
# T3
$v = (Get-Content "$I\VERSION.txt" -Raw).Trim(); $h = (Get-FileHash "$I\n8_runner.py").Hash.Substring(0,16).ToLower()
if ($v -notmatch 'build 6' -or $h -ne 'ba66c6fbbbfe9d4b') { W "XATO T3: $v / $h"; exit 1 }; W "OK T3: $v; n8_runner $h"
# T4
Copy-Item C:\ZG\build_exe\isolation_check.py "$I\_iso.py"; Push-Location $I; & "$I\python\python.exe" -E -s "$I\_iso.py" *> "$X\iso.txt"; $rc=$LASTEXITCODE; Pop-Location; Remove-Item "$I\_iso.py"
if ($rc -ne 0) { W "XATO T4"; exit 1 }; W ("OK T4: " + (Select-String "$X\iso.txt" -Pattern 'TASHQI').Line)
# T5
Push-Location $I; & "$I\python\python.exe" -E -s C:\ZG\build_exe\regress_check.py C:\ZG\build_exe\regress_ct.nii.gz "$X\regr" *> "$X\regr.txt"; $rc=$LASTEXITCODE; Pop-Location
if ($rc -ne 0) { W "XATO T5: $((Get-Content "$X\regr.txt" | Select -Last 2) -join ' | ')"; exit 1 }; W ("OK T5: " + ((Get-Content "$X\regr.txt" | Select-String 'OK').Line -join '; '))
# T6
(Get-Content C:\ZG\platform_test\p_setup.py -Raw).Replace('http://127.0.0.1:8010',"http://127.0.0.1:$P").Replace('C:\ZG\platform_test\workspace',"$I\workspace").Replace('C:\ZG\platform_test\test_seed.json',"$X\seed.json") | Set-Content "$X\setup.py" -Encoding utf8
& C:\ZS\venv\Scripts\python.exe "$X\setup.py" *> "$X\setup.txt"
Push-Location C:\ZG\platform_tests; $env:PYTHONPATH='C:\ZG\platform_tests\_lib;C:\ZG\platform_tests'; $env:UZ_BASE="http://127.0.0.1:$P"; $env:UZ_SEED="$X\seed.json"; $env:UZ_JOBS="$I\workspace\jobs"
& C:\ZS\venv\Scripts\python.exe -m pytest -rfE *> "$X\tests.txt"; $rc=$LASTEXITCODE; Pop-Location
$sum=(Get-Content "$X\tests.txt" | Select-Object -Last 1); if ($rc -ne 0) { W "XATO T6: $sum" } else { W "OK T6: $sum" }
# T7
$hh=(Invoke-WebRequest "http://127.0.0.1:$P/" -UseBasicParsing).Content; $js=[Text.Encoding]::UTF8.GetString((Invoke-WebRequest "http://127.0.0.1:$P/static/i18n.js" -UseBasicParsing).RawContentStream.ToArray()); $css=[Text.Encoding]::UTF8.GetString((Invoke-WebRequest "http://127.0.0.1:$P/static/style.css" -UseBasicParsing).RawContentStream.ToArray())
$ok7 = ($hh -match '<title>UzLungMSKT</title>') -and ($js -match 'Xavfli o.simta ehtimoli') -and ($css -match 'moslashuv 1.1') -and ((([regex]::Matches($hh,'\?v=(\d+)') | % { $_.Groups[1].Value } | sort -Unique)) -join ',') -eq '46'
if ($ok7) { W "OK T7: nom, В«Xavfli o'simta ehtimoliВ», mobil CSS, v=46" } else { W "XATO T7" }
# T8
$p8 = (Invoke-WebRequest 'http://localhost:8000/' -UseBasicParsing -TimeoutSec 10).StatusCode; W "OK T8: ishchi platforma 8000 javobi $p8"
Push-Location $I; & "$I\python\python.exe" -E -s -m uzlungct.autostart stop --port $P *> $null; Pop-Location
W "TUGADI"

