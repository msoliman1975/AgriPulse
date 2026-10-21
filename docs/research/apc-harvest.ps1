Add-Type -AssemblyName System.Web
$ErrorActionPreference = 'Stop'
$dir = 'C:\Users\MOSOLI~1\AppData\Local\Temp\claude\C--Users-mosoliman-projects-MissionAgre\e2f29f12-a981-4b7e-b90b-9692d2e5ab8d\scratchpad'
$url = 'http://www1.apc.gov.eg/en/products/showall.aspx'
$hdr = @{ 'Referer' = $url; 'User-Agent' = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126 Safari/537.36' }
$crops = @('Mango', 'Potato', 'Date palm', 'Dates')
$log = Join-Path $dir 'apc_harvest.log'
function Say($m) { Add-Content -Path $log -Value ((Get-Date -Format 'HH:mm:ss') + ' ' + $m) -Encoding utf8 }
function Clean($s) {
  if ($null -eq $s) { return '' }
  return (([System.Web.HttpUtility]::HtmlDecode(($s -replace '<[^>]+>', ' '))) -replace '\s+', ' ').Trim()
}
function HiddenFields($html) {
  $d = @{}
  foreach ($m in [regex]::Matches($html, '<input[^>]*type="hidden"[^>]*>')) {
    $n = [regex]::Match($m.Value, 'name="([^"]*)"'); if (-not $n.Success) { continue }
    $v = [regex]::Match($m.Value, 'value="([^"]*)"')
    $d[$n.Groups[1].Value] = if ($v.Success) { [System.Web.HttpUtility]::HtmlDecode($v.Groups[1].Value) } else { '' }
  }
  return $d
}
function Enc($d) {
  ($d.GetEnumerator() | ForEach-Object {
    [System.Web.HttpUtility]::UrlEncode($_.Key) + '=' + [System.Web.HttpUtility]::UrlEncode([string]$_.Value)
  }) -join '&'
}

Set-Content -Path $log -Value '' -Encoding utf8
$found = @{}

foreach ($crop in $crops) {
  $g = Invoke-WebRequest -Uri $url -UseBasicParsing -SessionVariable s -TimeoutSec 120
  $f = HiddenFields $g.Content
  $f['__EVENTTARGET'] = ''; $f['__EVENTARGUMENT'] = ''
  $f['ctl00$Searchbar1$TextBoxSearch'] = $crop
  $f['ctl00$Searchbar1$RadioButtonListCriteria'] = 'Crop Name'
  $f['ctl00$Searchbar1$btnSearchBar'] = 'Search'
  $r = Invoke-WebRequest -Uri $url -Method Post -Body (Enc $f) -Headers $hdr `
    -ContentType 'application/x-www-form-urlencoded' -WebSession $s -UseBasicParsing -TimeoutSec 300
  $total = [int]([regex]::Match($r.Content, '(\d+) Results Found').Groups[1].Value)
  Say ("$crop : $total results")
  [regex]::Matches($r.Content, 'href="(?:products/)?(\d+)/details\.aspx"') | ForEach-Object { $found[$_.Groups[1].Value] = $true }
  $pages = [Math]::Ceiling($total / 10)
  for ($p = 2; $p -le $pages; $p++) {
    $f2 = HiddenFields $r.Content
    $f2.Remove('ctl00$Searchbar1$btnSearchBar')
    $f2['__EVENTTARGET'] = 'ctl00$ContentPlaceHolder1$plResult$SearchResult_GV'
    $f2['__EVENTARGUMENT'] = ('Page$' + $p)
    try {
      $r = Invoke-WebRequest -Uri $url -Method Post -Body (Enc $f2) -Headers $hdr `
        -ContentType 'application/x-www-form-urlencoded' -WebSession $s -UseBasicParsing -TimeoutSec 300
      [regex]::Matches($r.Content, 'href="(?:products/)?(\d+)/details\.aspx"') | ForEach-Object { $found[$_.Groups[1].Value] = $true }
    } catch { Say ("  $crop page $p failed: " + $_.Exception.Message.Split("`n")[0]); break }
  }
  Say ("$crop done. running unique total " + $found.Count)
}

$ids = $found.Keys | Sort-Object { [int]$_ }
Set-Content -Path (Join-Path $dir 'apc_ids.txt') -Value ($ids -join "`n") -Encoding utf8
Say ('UNIQUE PRODUCT IDS: ' + $ids.Count)

$cropNames = @{ '115' = 'Mango'; '127' = 'Potato'; '107' = 'Date palm'; '1264' = 'Dates' }
$rows = New-Object System.Collections.ArrayList
$n = 0
foreach ($id in $ids) {
  $n++
  try {
    $d = (Invoke-WebRequest -Uri "http://www1.apc.gov.eg/en/products/$id/details.aspx" -UseBasicParsing -Headers $hdr -TimeoutSec 120).Content
  } catch { Say ("detail $id failed"); continue }

  $tbl = [regex]::Match($d, '(?s)id="ctl00_ContentPlaceHolder1_pdResult_dvProduct"(.*?)</table>\s*</div>')
  $kv = @{}
  if ($tbl.Success) {
    foreach ($tr in [regex]::Matches($tbl.Groups[1].Value, '(?s)<tr[^>]*>(.*?)</tr>')) {
      $tds = [regex]::Matches($tr.Groups[1].Value, '(?s)<td[^>]*>(.*?)</td>')
      if ($tds.Count -ge 2) { $kv[(Clean $tds[0].Groups[1].Value)] = (Clean $tds[1].Groups[1].Value) }
    }
  }
  $prod = [ordered]@{
    product_id    = $id
    reg_no        = $kv['Registration No.']
    cas_no        = $kv['CAS No']
    trade_name    = $kv['Trade Name']
    active_ing    = ($kv['Active Ingredients'] -replace ' \+ ', '+')
    concentration = $kv['Concentration']
    status        = $kv['Status']
    manufacturer  = $kv['Manufacturer']
    usage_class   = $kv['Usage Classification']
    who_class     = $kv['WHO Classification']
    formulation   = $kv['Formulation']
    country       = $kv['Country']
  }

  foreach ($blk in [regex]::Matches($d, '(?s)hfCropId"\s+value="(\d+)"(.*?)(?=hfCropId"\s+value="|MRL By Active)')) {
    $cid = $blk.Groups[1].Value
    if (-not $cropNames.ContainsKey($cid)) { continue }
    foreach ($rep in [regex]::Matches($blk.Groups[2].Value, '(?s)lblGSRestricationTitle.*?(?=lblGSRestricationTitle|$)')) {
      $h = $rep.Value
      $row = [ordered]@{}
      foreach ($k in $prod.Keys) { $row[$k] = $prod[$k] }
      $row['crop_id'] = $cid
      $row['crop'] = $cropNames[$cid]
      $row['crop_description'] = Clean ([regex]::Match($h, '(?s)_lblGsRestriction">(.*?)</span>').Groups[1].Value)
      $row['pest'] = Clean ([regex]::Match($h, '(?s)_lblPest">(.*?)</span>').Groups[1].Value)
      $row['rate'] = Clean ([regex]::Match($h, '(?s)_lblRate">(.*?)</span>').Groups[1].Value)
      $row['phi'] = Clean ([regex]::Match($h, '(?s)_lblPHI">(.*?)</span>').Groups[1].Value)
      $row['notes'] = Clean ([regex]::Match($h, '(?s)_lblNotes">(.*?)</span>').Groups[1].Value)
      [void]$rows.Add([pscustomobject]$row)
    }
  }
  if ($n % 25 -eq 0) { Say ("detail $n / " + $ids.Count + ' rows=' + $rows.Count) }
}
$rows | Export-Csv -Path (Join-Path $dir 'apc_register.csv') -NoTypeInformation -Encoding UTF8
Say ('DONE rows=' + $rows.Count + ' products=' + $ids.Count)
