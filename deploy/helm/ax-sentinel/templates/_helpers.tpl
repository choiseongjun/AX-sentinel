{{- define "ax-sentinel.labels" -}}
app.kubernetes.io/part-of: ax-sentinel
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end }}

{{- define "ax-sentinel.image" -}}
{{- if $.root.Values.global.imageRegistry -}}
{{ $.root.Values.global.imageRegistry }}/{{ $.service.image }}:{{ $.root.Values.global.imageTag }}
{{- else -}}
{{ $.service.image }}:{{ $.root.Values.global.imageTag }}
{{- end -}}
{{- end }}
