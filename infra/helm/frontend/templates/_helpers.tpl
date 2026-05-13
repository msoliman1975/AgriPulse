{{- define "missionagre-frontend.fullname" -}}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "missionagre-frontend.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (printf "%s-frontend" .Release.Name) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{- define "missionagre-frontend.imageRef" -}}
{{- $tag := default .Chart.AppVersion (default .Values.image.tag .Values.global.images.frontend.tag) -}}
{{- printf "%s:%s" .Values.image.repository $tag -}}
{{- end -}}

{{- define "missionagre-frontend.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: missionagre
app.kubernetes.io/component: frontend
{{- end -}}

{{- define "missionagre-frontend.selectorLabels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/component: frontend
{{- end -}}
