{{/*
Common helpers for the api chart. Mirrors the shape of the other service
charts so values.yaml fields and selector labels stay aligned.
*/}}

{{- define "agripulse-api.fullname" -}}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "agripulse-api.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (printf "%s-api" .Release.Name) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{- define "agripulse-api.imageRef" -}}
{{- /* Tag resolution order: overlay global.images.api.tag â†’ chart-local
       image.tag â†’ .Chart.AppVersion. The overlay map is bumped per-image
       by .github/workflows/argocd-sync.yml so api/workers/frontend/
       tileServer no longer share a single global tag. The chart's
       values.yaml seeds an empty global.images.api.tag so a bare
       `helm template` (without the overlay) still resolves. */ -}}
{{- $tag := default .Chart.AppVersion (default .Values.image.tag .Values.global.images.api.tag) -}}
{{- printf "%s:%s" .Values.image.repository $tag -}}
{{- end -}}

{{- define "agripulse-api.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: agripulse
app.kubernetes.io/component: api
{{- end -}}

{{- define "agripulse-api.selectorLabels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/component: api
{{- end -}}
