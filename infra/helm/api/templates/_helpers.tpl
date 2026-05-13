{{/*
Common helpers for the api chart. Mirrors the shape of the other service
charts so values.yaml fields and selector labels stay aligned.
*/}}

{{- define "missionagre-api.fullname" -}}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "missionagre-api.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (printf "%s-api" .Release.Name) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{- define "missionagre-api.imageRef" -}}
{{- /* Tag resolution order: overlay global.images.api.tag → chart-local
       image.tag → .Chart.AppVersion. The overlay map is bumped per-image
       by .github/workflows/argocd-sync.yml so api/workers/frontend/
       tileServer no longer share a single global tag. The chart's
       values.yaml seeds an empty global.images.api.tag so a bare
       `helm template` (without the overlay) still resolves. */ -}}
{{- $tag := default .Chart.AppVersion (default .Values.image.tag .Values.global.images.api.tag) -}}
{{- printf "%s:%s" .Values.image.repository $tag -}}
{{- end -}}

{{- define "missionagre-api.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: missionagre
app.kubernetes.io/component: api
{{- end -}}

{{- define "missionagre-api.selectorLabels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/component: api
{{- end -}}
