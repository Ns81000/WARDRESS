$ErrorActionPreference = 'Continue'
$base = 'http://localhost:8321'
$pw = (Get-Content .env | Select-String 'ADMIN_PASSWORD=').Line.Split('=')[1]
function Req($method, $path, $headers, $body) {
  $args2 = @{ Method = $method; Uri = "$base$path"; SkipHttpErrorCheck = $true }
  if ($headers) { $args2.Headers = $headers }
  if ($body) { $args2.ContentType = 'application/json'; $args2.Body = $body }
  return Invoke-WebRequest @args2
}
function Login($email, $password) {
  $r = Invoke-RestMethod -Method Post -Uri "$base/api/auth/login" -ContentType 'application/json' -Body (@{email=$email;password=$password}|ConvertTo-Json)
  return @{ token = $r.access_token; H = @{Authorization = "Bearer $($r.access_token)"} }
}
$admin = Login 'admin@wardress.local' $pw
$v = Req Post '/api/users' $admin.H (@{email='audit4c-viewer@example.test';password='AuditViewer-4c!x';role='viewer'}|ConvertTo-Json)
$a = Req Post '/api/users' $admin.H (@{email='audit4c-analyst@example.test';password='AuditAnalyst-4c!x';role='analyst'}|ConvertTo-Json)
"create viewer: $($v.StatusCode)  create analyst: $($a.StatusCode)"
$vid = ($v.Content|ConvertFrom-Json).id; $aid = ($a.Content|ConvertFrom-Json).id
$viewer = Login 'audit4c-viewer@example.test' 'AuditViewer-4c!x'
$analyst = Login 'audit4c-analyst@example.test' 'AuditAnalyst-4c!x'
$r = Req Get '/api/users' $viewer.H; "users-as-viewer: $($r.StatusCode) $($r.Content)"
$r = Req Post '/api/sites' $viewer.H (@{name='x';url='https://example.com'}|ConvertTo-Json); "create-site-as-viewer: $($r.StatusCode) $($r.Content)"
$r = Req Get '/api/api-keys' $viewer.H; "apikeys-as-viewer: $($r.StatusCode)"
$r = Req Post '/api/api-keys' $viewer.H (@{label='nope'}|ConvertTo-Json); "apikey-create-as-viewer: $($r.StatusCode) $($r.Content)"
$r = Req Post '/api/api-keys' $analyst.H (@{label='audit4c'}|ConvertTo-Json); "apikey-create-as-analyst: $($r.StatusCode)"
$raw = ($r.Content|ConvertFrom-Json).key
$KH = @{Authorization = "Bearer $raw"}
$r = Req Get '/api/sites' $KH; "sites-via-apikey: $($r.StatusCode)"
$r = Req Post '/api/api-keys' $KH (@{label='cascade'}|ConvertTo-Json); "apikey-create-via-apikey: $($r.StatusCode) $($r.Content)"
$r = Req Post '/api/auth/logout' $KH; "logout-via-apikey: $($r.StatusCode) $($r.Content)"
$r = Req Post '/api/alerts/00000000-0000-0000-0000-000000000000/ack' $viewer.H; "ack-as-viewer: $($r.StatusCode) $($r.Content)"
$r = Req Post '/api/sites/00000000-0000-0000-0000-000000000000/scans/00000000-0000-0000-0000-000000000000/explain' $viewer.H; "explain-as-viewer: $($r.StatusCode)"
$r = Req Post '/api/sites/bulk-import' $analyst.H (@{sitemap_url='https://example.com/sitemap.xml';allow_private_networks=$true}|ConvertTo-Json); "sitemap-private-as-analyst: $($r.StatusCode) $($r.Content)"
$r = Req Post '/api/agent/conversations' $viewer.H; "conv-as-viewer: $($r.StatusCode)"
$cid = ($r.Content|ConvertFrom-Json).id
$r = Req Get "/api/agent/conversations/$cid" $admin.H; "conv-foreign-as-admin: $($r.StatusCode) $($r.Content)"
$r = Req Post '/api/sites' $analyst.H (@{name='Audit4C Example';url='https://example.com/';scan_interval_minutes=3600}|ConvertTo-Json); "create-site-analyst: $($r.StatusCode) interval-out-of-range"
$r = Req Post '/api/sites' $analyst.H (@{name='Audit4C Example';url='https://example.com/'}|ConvertTo-Json); "create-site-ok: $($r.StatusCode)"
$site = ($r.Content|ConvertFrom-Json); $sid = $site.id
"site: next_scan_at=$($site.next_scan_at) baseline_id=$($site.baseline_id)"
$r = Req Post "/api/sites/$sid/scan-now" $analyst.H; "scan-now-no-baseline: $($r.StatusCode) $($r.Content)"
$r = Req Post "/api/sites/$sid/rebaseline" $analyst.H; "rebaseline-inflight: $($r.StatusCode) $($r.Content)"
$r = Req Get "/api/sites/$sid" $admin.H; "site-as-admin: $($r.StatusCode) baseline_status=$(((($r.Content)|ConvertFrom-Json).baseline_status))"
$r = Req Delete "/api/sites/$sid" $analyst.H; "delete-site: $($r.StatusCode)"
$r = Req Delete "/api/sites/$sid" $analyst.H; "delete-site-replay: $($r.StatusCode) $($r.Content)"
$r = Req Delete "/api/users/$vid" $admin.H; "delete-viewer: $($r.StatusCode)"
$users = (Invoke-RestMethod "$base/api/users" -Headers $admin.H)
"viewer still listed: $([bool]($users | Where-Object id -eq $vid))"
$lim = 0; $ra = ''
for ($i=0; $i -lt 35; $i++) {
  $r = Req Post '/api/auth/login' $null (@{email='ghost@example.test';password='x'}|ConvertTo-Json)
  if ($r.StatusCode -eq 429) { $lim++; $ra = $r.Headers['Retry-After'] }
}
"login-429s: $lim of 35  Retry-After=$ra"
$audit = Invoke-RestMethod "$base/api/audit-log?limit=200" -Headers $admin.H
"audit rows referencing deleted viewer: $((($audit.items) | Where-Object { $_.actor_id -eq $vid }).Count)"
"audit actions sample: $(($audit.items | Select-Object -First 12 | ForEach-Object action) -join ', ')"
