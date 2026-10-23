{{/*
Expand the name of the chart.
*/}}
{{- define "offroad-scraper.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this.
*/}}
{{- define "offroad-scraper.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "offroad-scraper.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels.
*/}}
{{- define "offroad-scraper.labels" -}}
helm.sh/chart: {{ include "offroad-scraper.chart" . }}
{{ include "offroad-scraper.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels.
*/}}
{{- define "offroad-scraper.selectorLabels" -}}
app.kubernetes.io/name: {{ include "offroad-scraper.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Name of the shared PVC used to persist `/data`.
*/}}
{{- define "offroad-scraper.pvcName" -}}
{{- printf "%s-pvc" (include "offroad-scraper.fullname" .) }}
{{- end }}

{{/*
Name of the ConfigMap holding `sites.yaml`.
*/}}
{{- define "offroad-scraper.configName" -}}
{{- printf "%s-config" (include "offroad-scraper.fullname" .) }}
{{- end }}

{{/*
Name of the Secret referenced by the workloads.

In `values` and `external` modes the Secret is `<fullname>-secret`. In
`existing` mode we reference the user-provided pre-created Secret name.
*/}}
{{- define "offroad-scraper.secretName" -}}
{{- if eq .Values.secret.mode "existing" }}
{{- required "secret.existing.name is required when secret.mode is 'existing'" .Values.secret.existing.name }}
{{- else }}
{{- printf "%s-secret" (include "offroad-scraper.fullname" .) }}
{{- end }}
{{- end }}

{{/*
Environment variables common to both the `serve` and `scrape` workloads.
*/}}
{{- define "offroad-scraper.commonEnv" -}}
- name: LOG_LEVEL
  value: {{ .Values.config.logLevel | quote }}
- name: HOST
  value: {{ .Values.config.host | quote }}
- name: PORT
  value: {{ .Values.config.port | int | quote }}
- name: SITES_FILE
  value: {{ .Values.config.sitesFile | quote }}
- name: OUTPUT_DIR
  value: {{ .Values.config.outputDir | quote }}
{{- end }}

{{/*
Environment variables specific to the `scrape` workload (LLM extraction).
*/}}
{{- define "offroad-scraper.scrapeEnv" -}}
- name: DEEPSEEK_API_KEY
  valueFrom:
    secretKeyRef:
      name: {{ include "offroad-scraper.secretName" . }}
      key: DEEPSEEK_API_KEY
- name: DEEPSEEK_BASE_URL
  value: {{ .Values.config.deepseek.baseUrl | quote }}
- name: DEEPSEEK_MODEL
  value: {{ .Values.config.deepseek.model | quote }}
- name: DEEPSEEK_TIMEOUT_SECONDS
  value: {{ .Values.config.deepseek.timeoutSeconds | int | quote }}
- name: DEEPSEEK_MAX_TOKENS
  value: {{ .Values.config.deepseek.maxTokens | int | quote }}
- name: DEEPSEEK_TEMPERATURE
  value: {{ .Values.config.deepseek.temperature | quote }}
- name: EXTRACT_MAX_RETRIES
  value: {{ .Values.config.extractMaxRetries | int | quote }}
- name: SCRAPE_TIMEOUT_SECONDS
  value: {{ .Values.config.scrape.timeoutSeconds | int | quote }}
- name: SCRAPE_MAX_BYTES
  value: {{ .Values.config.scrape.maxBytes | int | quote }}
- name: SCRAPE_USER_AGENT
  value: {{ .Values.config.scrape.userAgent | quote }}
- name: RETENTION_DAYS
  value: {{ .Values.config.retentionDays | int | quote }}
- name: HOME_LOCATION
  value: {{ .Values.config.cost.homeLocation | quote }}
- name: VEHICLE_DESCRIPTION
  value: {{ .Values.config.cost.vehicleDescription | quote }}
- name: FUEL_CONSUMPTION_L_100KM
  value: {{ .Values.config.cost.fuelConsumptionL100km | quote }}
- name: DIESEL_PRICE_EUR
  value: {{ .Values.config.cost.dieselPriceEur | quote }}
- name: PLN_TO_EUR
  value: {{ .Values.config.cost.plnToEur | quote }}
{{- end }}

{{/*
Environment variables specific to the `serve` workload (auth + caching).
*/}}
{{- define "offroad-scraper.serveEnv" -}}
- name: ICS_AUTH_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ include "offroad-scraper.secretName" . }}
      key: ICS_AUTH_PASSWORD
      optional: true
- name: SUBSCRIPTION_TOKEN
  valueFrom:
    secretKeyRef:
      name: {{ include "offroad-scraper.secretName" . }}
      key: SUBSCRIPTION_TOKEN
      optional: true
- name: ALLOWED_EMAILS
  value: {{ join "," .Values.allowedEmails | quote }}
- name: ICS_CACHE_MAX_AGE
  value: {{ .Values.config.icsCacheMaxAge | int | quote }}
- name: PUBLISHED_TTL
  value: {{ .Values.config.publishedTtl | int | quote }}
{{- end }}
