{{- define "agripulse-workers.fullname" -}}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "agripulse-workers.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (printf "%s-workers" .Release.Name) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{- define "agripulse-workers.imageRef" -}}
{{- /* See api chart helper. Overlay key is `workers` even though workers
       reuse the API image â€” bumping both keeps the audit trail per-image. */ -}}
{{- $tag := default .Chart.AppVersion (default .Values.image.tag .Values.global.images.workers.tag) -}}
{{- printf "%s:%s" .Values.image.repository $tag -}}
{{- end -}}

{{- define "agripulse-workers.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: agripulse
{{- end -}}

{{/* selectorLabels for a specific workload (light|heavy|beat). */}}
{{- define "agripulse-workers.selectorLabels" -}}
app.kubernetes.io/name: {{ .root.Chart.Name }}
app.kubernetes.io/instance: {{ .root.Release.Name }}
app.kubernetes.io/component: {{ printf "worker-%s" .name }}
{{- end -}}
