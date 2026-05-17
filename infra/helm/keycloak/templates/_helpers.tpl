{{/*
Shared helpers for the agripulse-keycloak chart.
*/}}

{{- define "agripulse-keycloak.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
app.kubernetes.io/name: agripulse-keycloak
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: agripulse
{{- end -}}

{{/*
The promote-bootstrap Job runs from the api image — it has /app/scripts/
dev_bootstrap.py in PYTHONPATH and uv-installed httpx. Tag follows the
same resolution order as the api chart so a hand-bump in
overlays/<env>/values.yaml.global.images.api.tag propagates here too,
without needing a parallel toggle.
*/}}
{{- define "agripulse-keycloak.apiImageRef" -}}
{{- $repo := default "ghcr.io/msoliman1975/agripulse/api" .Values.promoteBootstrap.apiImage.repository -}}
{{- $tag := default "" .Values.global.images.api.tag -}}
{{- if not $tag -}}
{{- $tag = default "latest" .Values.promoteBootstrap.apiImage.tag -}}
{{- end -}}
{{- printf "%s:%s" $repo $tag -}}
{{- end -}}
