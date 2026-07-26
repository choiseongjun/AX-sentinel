import {
  Activity,
  AlertTriangle,
  BarChart3,
  Bot,
  CheckCircle2,
  ChevronRight,
  ClipboardCheck,
  Factory,
  FileSearch,
  Gauge,
  LayoutDashboard,
  LogOut,
  Menu,
  Pause,
  Play,
  Radio,
  Search,
  ShieldCheck,
  Siren,
  Upload,
  Wrench,
  X,
} from "lucide-react";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import {
  beginSignIn,
  getAccessToken,
  isCognitoEnabled,
  restoreUser,
  roleFromUser,
  signOut,
} from "./auth";

type Page =
  | "dashboard"
  | "live-data"
  | "equipment"
  | "incidents"
  | "analysis"
  | "work-orders"
  | "documents"
  | "metrics";

type Incident = {
  id: string;
  equipment_id: string;
  status: string;
  severity: string;
  detected_at: string;
  payload: {
    sensor_type: string;
    measured_value: number;
    threshold: number;
    error_code: string;
    log_excerpt: string;
  };
};

type Equipment = {
  id: string;
  name: string;
  line: string;
  model: string;
  status: string;
  last_seen_at: string;
};

type Analysis = {
  id: string;
  incident_id: string;
  risk_level: string;
  confidence: number;
  causes: { cause: string; confidence: number; evidence: string[] }[];
  related_document_ids: string[];
  recommended_actions: {
    sequence: number;
    instruction: string;
    hazardous: boolean;
    requires_shutdown: boolean;
  }[];
  expert_review_required: boolean;
  manager_approval_required: boolean;
  review_reasons: string[];
  executable: boolean;
};

type WorkOrder = {
  id: string;
  incident_id: string;
  analysis_id: string;
  status: string;
  checklist: string[];
  completed_items: string[];
  recovery_confirmed: boolean;
};

type Metrics = {
  analysis_count: number;
  expert_review_rate: number;
  cause_accuracy_average: number;
  action_usefulness_average: number;
};

type KnowledgeHit = {
  content: string;
  score: number;
  location: string;
  document_id: string;
};

type Telemetry = {
  id: string;
  equipment_id: string;
  sensor_type: string;
  measured_value: number;
  unit: string;
  threshold: number;
  status: "normal" | "warning" | "critical";
  received_at: string;
  log_excerpt: string;
};

const navItems = [
  { id: "dashboard" as Page, label: "운영 대시보드", icon: LayoutDashboard },
  { id: "live-data" as Page, label: "실시간 데이터", icon: Radio },
  { id: "equipment" as Page, label: "설비 관리", icon: Factory },
  { id: "incidents" as Page, label: "장애 관리", icon: Siren },
  { id: "work-orders" as Page, label: "작업 티켓", icon: ClipboardCheck },
  { id: "documents" as Page, label: "문서 관리", icon: FileSearch },
  { id: "metrics" as Page, label: "AI 운영 지표", icon: BarChart3 },
];

async function api<T>(url: string, options?: RequestInit): Promise<T> {
  const token = await getAccessToken();
  const headers = new Headers(options?.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(url, { ...options, headers });
  if (!response.ok) {
    const error = await response.text();
    throw new Error(error || `HTTP ${response.status}`);
  }
  return response.json() as Promise<T>;
}

function Login({ onLogin }: { onLogin: (role: string) => void }) {
  const [role, setRole] = useState("operator_manager");
  return (
    <div className="login-shell">
      <section className="login-visual">
        <div className="brand-mark large"><ShieldCheck /></div>
        <p className="eyebrow">INDUSTRIAL INTELLIGENCE</p>
        <h1>멈추기 전에 감지하고,<br />위험해지기 전에 대응합니다.</h1>
        <p className="login-copy">
          설비 신호와 현장 지식을 연결해 더 빠르고 안전한 장애 대응을 지원합니다.
        </p>
        <div className="signal-grid">
          {[32, 48, 38, 72, 54, 88, 64, 42, 58, 35, 78, 48].map((height, index) => (
            <span key={index} style={{ height: `${height}px` }} />
          ))}
        </div>
      </section>
      <section className="login-panel">
        <div className="login-card">
          <div className="brand-row">
            <div className="brand-mark"><ShieldCheck /></div>
            <div><strong>AX Sentinel</strong><span>설비 장애 대응 플랫폼</span></div>
          </div>
          <h2>운영 콘솔 로그인</h2>
          <p>로컬 개발 환경의 사용자 역할을 선택하세요.</p>
          {!isCognitoEnabled() && (
            <>
              <label>사용자 역할</label>
              <select value={role} onChange={(event) => setRole(event.target.value)}>
                <option value="operator_manager">운영 관리자</option>
                <option value="field_worker">현장 작업자</option>
                <option value="system_admin">시스템 관리자</option>
              </select>
            </>
          )}
          <button
            className="primary wide"
            onClick={() => isCognitoEnabled() ? beginSignIn() : onLogin(role)}
          >
            {isCognitoEnabled() ? "Cognito로 로그인" : "로컬 콘솔 시작"} <ChevronRight size={18} />
          </button>
          <div className="security-note">
            <ShieldCheck size={16} />
            운영 환경에서는 Cognito OIDC와 MFA로 보호됩니다.
          </div>
        </div>
      </section>
    </div>
  );
}

function App() {
  const [role, setRole] = useState<string | null>(null);
  const [page, setPage] = useState<Page>("dashboard");
  const [mobileOpen, setMobileOpen] = useState(false);
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [equipment, setEquipment] = useState<Equipment[]>([]);
  const [workOrders, setWorkOrders] = useState<WorkOrder[]>([]);
  const [metrics, setMetrics] = useState<Metrics>({
    analysis_count: 0,
    expert_review_rate: 0,
    cause_accuracy_average: 0,
    action_usefulness_average: 0,
  });
  const [selectedIncident, setSelectedIncident] = useState<Incident | null>(null);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [notice, setNotice] = useState("");
  const [authLoading, setAuthLoading] = useState(isCognitoEnabled());

  useEffect(() => {
    if (!isCognitoEnabled()) return;
    restoreUser()
      .then((user) => user && setRole(roleFromUser(user)))
      .catch((error) => setNotice(String(error)))
      .finally(() => setAuthLoading(false));
  }, []);

  const refresh = useCallback(async () => {
    const [incidentData, equipmentData, orderData, metricData] = await Promise.all([
      api<Incident[]>("/api/v1/incidents"),
      api<Equipment[]>("/api/v1/equipment"),
      api<WorkOrder[]>("/api/v1/work-orders"),
      api<Metrics>("/api/v1/metrics/summary"),
    ]);
    setIncidents(incidentData);
    setEquipment(equipmentData);
    setWorkOrders(orderData);
    setMetrics(metricData);
  }, []);

  useEffect(() => {
    if (role) refresh().catch((error) => setNotice(error.message));
  }, [role, refresh]);

  const openIncident = (incident: Incident) => {
    setSelectedIncident(incident);
    setAnalysis(null);
    setPage("analysis");
  };

  if (authLoading) return <div className="auth-loading"><ShieldCheck /><span>보안 세션 확인 중...</span></div>;
  if (!role) return <Login onLogin={setRole} />;

  return (
    <div className="app-shell">
      <aside className={mobileOpen ? "sidebar open" : "sidebar"}>
        <div className="brand-row sidebar-brand">
          <div className="brand-mark"><ShieldCheck /></div>
          <div><strong>AX Sentinel</strong><span>Operations</span></div>
          <button className="icon-button close-menu" onClick={() => setMobileOpen(false)}><X /></button>
        </div>
        <nav>
          <p className="nav-label">OPERATIONS</p>
          {navItems.map((item) => (
            <button
              key={item.id}
              className={page === item.id ? "nav-item active" : "nav-item"}
              onClick={() => { setPage(item.id); setMobileOpen(false); }}
            >
              <item.icon size={19} /> {item.label}
              {item.id === "incidents" && incidents.length > 0 && (
                <span className="nav-badge">{incidents.length}</span>
              )}
            </button>
          ))}
        </nav>
        <div className="system-card">
          <div><span className="status-dot" /> 시스템 정상</div>
          <small>6개 서비스 연결됨</small>
        </div>
        <button className="user-card" onClick={() => isCognitoEnabled() ? signOut() : setRole(null)}>
          <span className="avatar">{role === "field_worker" ? "현" : role === "system_admin" ? "시" : "운"}</span>
          <span><strong>{roleLabel(role)}</strong><small>로컬 사용자</small></span>
          <LogOut size={17} />
        </button>
      </aside>

      <main>
        <header className="topbar">
          <button className="icon-button menu-button" onClick={() => setMobileOpen(true)}><Menu /></button>
          <div>
            <p className="breadcrumb">AX SENTINEL / {pageTitle(page)}</p>
            <h2>{pageTitle(page)}</h2>
          </div>
          <div className="topbar-actions">
            <span className="live-pill"><span className="status-dot" /> LIVE</span>
            <span className="timestamp">{new Date().toLocaleString("ko-KR")}</span>
          </div>
        </header>
        {notice && <div className="notice" onClick={() => setNotice("")}>{notice}</div>}
        <div className="content">
          {page === "dashboard" && <Dashboard incidents={incidents} equipment={equipment} metrics={metrics} onIncident={openIncident} />}
          {page === "live-data" && <LiveDataPage setNotice={setNotice} />}
          {page === "equipment" && <EquipmentPage equipment={equipment} />}
          {page === "incidents" && <IncidentsPage incidents={incidents} refresh={refresh} onIncident={openIncident} setNotice={setNotice} />}
          {page === "analysis" && selectedIncident && (
            <AnalysisPage
              incident={selectedIncident}
              analysis={analysis}
              setAnalysis={setAnalysis}
              refresh={refresh}
              setNotice={setNotice}
            />
          )}
          {page === "analysis" && !selectedIncident && <EmptyState title="분석할 장애를 선택하세요" onClick={() => setPage("incidents")} />}
          {page === "work-orders" && <WorkOrdersPage workOrders={workOrders} role={role} refresh={refresh} setNotice={setNotice} />}
          {page === "documents" && <DocumentsPage setNotice={setNotice} />}
          {page === "metrics" && <MetricsPage metrics={metrics} />}
        </div>
      </main>
    </div>
  );
}

const demoSensors = [
  { equipment_id: "PRESS-001", sensor_type: "bearing_temperature", unit: "°C", threshold: 90, base: 72 },
  { equipment_id: "PRESS-001", sensor_type: "vibration_rms", unit: "mm/s", threshold: 10, base: 6.2 },
  { equipment_id: "MOTOR-002", sensor_type: "motor_current", unit: "A", threshold: 42, base: 31 },
];

function LiveDataPage({ setNotice }: { setNotice: (value: string) => void }) {
  const [records, setRecords] = useState<Telemetry[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [connected, setConnected] = useState(false);

  const loadTelemetry = useCallback(async () => {
    try {
      const data = await api<Telemetry[]>("/api/v1/telemetry?limit=100");
      setRecords(data);
      setConnected(true);
    } catch (error) {
      setConnected(false);
      setNotice(`실시간 데이터 연결 실패: ${String(error)}`);
    }
  }, [setNotice]);

  const sendDemoSample = useCallback(async () => {
    const sensor = demoSensors[Math.floor(Math.random() * demoSensors.length)];
    const spike = Math.random() > 0.88 ? sensor.threshold * (0.15 + Math.random() * 0.25) : 0;
    const noise = sensor.base * (Math.random() - 0.5) * 0.12;
    const value = Number((sensor.base + noise + spike).toFixed(2));
    await api<Telemetry>("/api/v1/telemetry", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        equipment_id: sensor.equipment_id,
        sensor_type: sensor.sensor_type,
        measured_value: value,
        unit: sensor.unit,
        threshold: sensor.threshold,
        log_excerpt: value >= sensor.threshold
          ? `${sensor.sensor_type} threshold exceeded`
          : `${sensor.sensor_type} sample received`,
      }),
    });
    await loadTelemetry();
  }, [loadTelemetry]);

  useEffect(() => {
    loadTelemetry();
    const poller = window.setInterval(loadTelemetry, 2000);
    return () => window.clearInterval(poller);
  }, [loadTelemetry]);

  useEffect(() => {
    if (!streaming) return;
    sendDemoSample().catch((error) => setNotice(String(error)));
    const producer = window.setInterval(
      () => sendDemoSample().catch((error) => setNotice(String(error))),
      1500,
    );
    return () => window.clearInterval(producer);
  }, [streaming, sendDemoSample, setNotice]);

  const latestBySensor = useMemo(() => {
    const result = new Map<string, Telemetry>();
    records.forEach((record) => {
      const key = `${record.equipment_id}:${record.sensor_type}`;
      if (!result.has(key)) result.set(key, record);
    });
    return [...result.values()];
  }, [records]);

  const chartRecords = [...records].slice(0, 36).reverse();
  const abnormalCount = records.filter((record) => record.status !== "normal").length;

  return (
    <div className="live-data-page">
      <section className="stream-toolbar panel">
        <div>
          <div className="stream-title">
            <span className={connected ? "pulse connected" : "pulse"} />
            <div><h3>센서 수신 스트림</h3><p>2초마다 최신 데이터를 확인합니다.</p></div>
          </div>
        </div>
        <div className="stream-actions">
          <span className="stream-count">{records.length} samples</span>
          <button className={streaming ? "danger-ghost" : "primary"} onClick={() => setStreaming((value) => !value)}>
            {streaming ? <Pause size={16} /> : <Play size={16} />}
            {streaming ? "데모 스트림 중지" : "데모 스트림 시작"}
          </button>
        </div>
      </section>

      <section className="live-kpis">
        <Kpi icon={Radio} label="연결 상태" value={connected ? "ONLINE" : "OFFLINE"} trend="Incident service" tone={connected ? "green" : "red"} />
        <Kpi icon={Activity} label="수신 데이터" value={records.length} unit="건" trend="최근 100건" tone="blue" />
        <Kpi icon={AlertTriangle} label="이상 신호" value={abnormalCount} unit="건" trend="임계치 기준" tone="amber" />
        <Kpi icon={Gauge} label="최근 수신" value={records[0] ? new Date(records[0].received_at).toLocaleTimeString("ko-KR") : "-"} trend="자동 갱신" tone="violet" />
      </section>

      <section className="sensor-card-grid">
        {latestBySensor.map((record) => (
          <article className={`sensor-live-card ${record.status}`} key={`${record.equipment_id}:${record.sensor_type}`}>
            <div className="sensor-card-head">
              <span>{record.equipment_id}</span>
              <span className={`status-label ${record.status}`}>{record.status}</span>
            </div>
            <p>{sensorLabel(record.sensor_type)}</p>
            <strong>{record.measured_value}<small>{record.unit}</small></strong>
            <div className="threshold-track"><i style={{ width: `${Math.min(record.measured_value / record.threshold * 100, 100)}%` }} /></div>
            <small>임계치 {record.threshold} {record.unit}</small>
          </article>
        ))}
      </section>

      <section className="live-grid">
        <div className="panel">
          <PanelHeader title="수신 파형" subtitle="최근 36개 샘플의 임계치 대비 측정값" />
          <div className="telemetry-chart">
            {chartRecords.length ? chartRecords.map((record) => (
              <span
                key={record.id}
                className={record.status}
                style={{ height: `${Math.max(8, Math.min(record.measured_value / record.threshold * 82, 100))}%` }}
                title={`${record.equipment_id} ${record.measured_value}${record.unit}`}
              />
            )) : <div className="chart-empty">데모 스트림을 시작하면 파형이 표시됩니다.</div>}
            <i className="threshold-line"><small>THRESHOLD</small></i>
          </div>
        </div>
        <div className="panel log-stream">
          <PanelHeader title="실시간 로그" subtitle="최근 수신 메시지" />
          {records.slice(0, 8).map((record) => (
            <div className="log-line" key={record.id}>
              <time>{new Date(record.received_at).toLocaleTimeString("ko-KR")}</time>
              <span className={record.status}>{record.status.toUpperCase()}</span>
              <p>{record.log_excerpt || `${record.sensor_type} sample received`}</p>
            </div>
          ))}
          {!records.length && <p className="table-empty">수신된 로그가 없습니다.</p>}
        </div>
      </section>

      <section className="panel">
        <PanelHeader title="최근 수신 데이터" subtitle="설비 게이트웨이에서 전달된 원본 센서 데이터" />
        <div className="table-wrap">
          <table>
            <thead><tr><th>수신 시각</th><th>설비</th><th>센서</th><th>측정값</th><th>임계치</th><th>상태</th></tr></thead>
            <tbody>
              {records.slice(0, 20).map((record) => (
                <tr key={record.id}>
                  <td>{new Date(record.received_at).toLocaleString("ko-KR")}</td>
                  <td><strong>{record.equipment_id}</strong></td>
                  <td>{sensorLabel(record.sensor_type)}</td>
                  <td>{record.measured_value} <small>{record.unit}</small></td>
                  <td>{record.threshold} <small>{record.unit}</small></td>
                  <td><span className={`status-label ${record.status}`}>{record.status}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function sensorLabel(value: string) {
  const labels: Record<string, string> = {
    bearing_temperature: "베어링 온도",
    vibration_rms: "진동 RMS",
    motor_current: "모터 전류",
  };
  return labels[value] ?? value;
}

function Dashboard({ incidents, equipment, metrics, onIncident }: {
  incidents: Incident[]; equipment: Equipment[]; metrics: Metrics; onIncident: (incident: Incident) => void;
}) {
  const critical = incidents.filter((item) => item.severity === "critical").length;
  return (
    <>
      <div className="hero-strip">
        <div><p className="eyebrow">PLANT STATUS</p><h3>오늘의 설비 운영 상태</h3><p>AI가 현장 신호를 지속적으로 감시하고 있습니다.</p></div>
        <div className="hero-score"><Gauge /><strong>92</strong><span>운영 건전성</span></div>
      </div>
      <section className="kpi-grid">
        <Kpi icon={Factory} label="연결 설비" value={equipment.length} unit="대" trend="정상 연결" tone="blue" />
        <Kpi icon={AlertTriangle} label="활성 장애" value={incidents.length} unit="건" trend={`${critical}건 긴급`} tone="red" />
        <Kpi icon={Bot} label="AI 분석" value={metrics.analysis_count} unit="건" trend="누적 평가" tone="violet" />
        <Kpi icon={CheckCircle2} label="원인 정확도" value={metrics.cause_accuracy_average || 0} unit="/ 5" trend="현장 피드백" tone="green" />
      </section>
      <section className="dashboard-grid">
        <div className="panel span-2">
          <PanelHeader title="최근 장애 이벤트" subtitle="우선순위가 높은 순서로 표시됩니다." />
          <IncidentTable incidents={incidents.slice(0, 6)} onIncident={onIncident} />
        </div>
        <div className="panel">
          <PanelHeader title="설비 상태 분포" subtitle="실시간 연결 설비 기준" />
          <div className="donut-wrap">
            <div className="donut"><strong>{equipment.length}</strong><span>전체 설비</span></div>
            <div className="legend">
              <span><i className="green" /> 정상 <b>{Math.max(equipment.length - 1, 0)}</b></span>
              <span><i className="amber" /> 주의 <b>{equipment.length ? 1 : 0}</b></span>
              <span><i className="red" /> 위험 <b>0</b></span>
            </div>
          </div>
        </div>
      </section>
    </>
  );
}

function IncidentsPage({ incidents, refresh, onIncident, setNotice }: {
  incidents: Incident[]; refresh: () => Promise<void>; onIncident: (incident: Incident) => void; setNotice: (value: string) => void;
}) {
  const simulate = async () => {
    try {
      await api<Incident>("/api/v1/incidents/simulate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          equipment_id: "PRESS-001",
          sensor_type: "bearing_temperature",
          measured_value: 112.4,
          threshold: 90,
          error_code: "E-BRG-017",
          log_excerpt: "Drive bearing temperature rose rapidly",
        }),
      });
      await refresh();
      setNotice("가상 설비 이상 이벤트가 생성되었습니다.");
    } catch (error) { setNotice(String(error)); }
  };
  return (
    <div className="panel">
      <div className="panel-actions">
        <PanelHeader title="장애 이벤트" subtitle="감지부터 복구까지 전체 이력을 관리합니다." />
        <button className="primary" onClick={simulate}><Activity size={17} /> 가상 이상 발생</button>
      </div>
      <IncidentTable incidents={incidents} onIncident={onIncident} />
    </div>
  );
}

function AnalysisPage({ incident, analysis, setAnalysis, refresh, setNotice }: {
  incident: Incident; analysis: Analysis | null; setAnalysis: (value: Analysis) => void;
  refresh: () => Promise<void>; setNotice: (value: string) => void;
}) {
  const [loading, setLoading] = useState(false);
  const runAnalysis = async () => {
    setLoading(true);
    try {
      if (incident.status === "detected") {
        await api(`/api/v1/incidents/${incident.id}/status`, {
          method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status: "analyzing" }),
        });
      }
      const result = await api<Analysis>("/api/v1/analyses", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          incident_id: incident.id,
          equipment_id: incident.equipment_id,
          sensor_summary: `${incident.payload.sensor_type}: ${incident.payload.measured_value} / threshold ${incident.payload.threshold}`,
          log_summary: `${incident.payload.error_code}: ${incident.payload.log_excerpt}`,
          related_document_ids: [],
        }),
      });
      setAnalysis(result);
      await api(`/api/v1/incidents/${incident.id}/status`, {
        method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status: "review_required" }),
      });
      await refresh();
    } catch (error) { setNotice(String(error)); } finally { setLoading(false); }
  };
  const approve = async () => {
    if (!analysis) return;
    try {
      await api<WorkOrder>("/api/v1/approvals", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ analysis_id: analysis.id, incident_id: incident.id, decision: "approve", reviewer_id: "local-manager", comment: "분석 근거와 안전 절차 확인 후 승인", checklist: analysis.recommended_actions.map((item) => item.instruction) }),
      });
      await api(`/api/v1/incidents/${incident.id}/status`, {
        method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status: "approved" }),
      });
      await refresh();
      setNotice("조치안이 승인되어 작업 티켓이 생성되었습니다.");
    } catch (error) { setNotice(String(error)); }
  };
  return (
    <div className="analysis-layout">
      <section className="panel">
        <PanelHeader title={`장애 ${incident.id.slice(0, 8)}`} subtitle={`${incident.equipment_id} · ${incident.payload.error_code}`} />
        <div className="sensor-reading"><span>{incident.payload.sensor_type}</span><strong>{incident.payload.measured_value}</strong><small>임계값 {incident.payload.threshold}</small></div>
        <div className="log-box">{incident.payload.log_excerpt}</div>
        <button className="primary wide" onClick={runAnalysis} disabled={loading}>
          <Bot size={18} /> {loading ? "근거를 분석하는 중..." : "AI 원인 분석 실행"}
        </button>
      </section>
      <section className="panel analysis-result">
        {!analysis ? (
          <div className="empty-analysis"><Bot size={42} /><h3>분석 대기 중</h3><p>센서, 로그, 정비 이력과 관련 문서를 함께 분석합니다.</p></div>
        ) : (
          <>
            <div className="risk-header">
              <div><p className="eyebrow">AI DIAGNOSIS</p><h3>분석 결과</h3></div>
              <span className={`severity ${analysis.risk_level}`}>{analysis.risk_level.toUpperCase()}</span>
            </div>
            <div className="confidence"><span>분석 신뢰도</span><div><i style={{ width: `${analysis.confidence * 100}%` }} /></div><strong>{Math.round(analysis.confidence * 100)}%</strong></div>
            {analysis.expert_review_required && <div className="review-warning"><AlertTriangle /> 관련 근거가 부족하여 전문가 검토가 필요합니다.</div>}
            <h4>원인 후보</h4>
            {analysis.causes.map((cause) => <div className="cause-card" key={cause.cause}><strong>{cause.cause}</strong><span>{Math.round(cause.confidence * 100)}%</span><p>{cause.evidence.join(" · ")}</p></div>)}
            <h4>권장 조치 계획</h4>
            <ol className="action-list">{analysis.recommended_actions.map((action) => <li key={action.sequence}><span>{action.sequence}</span><div>{action.instruction}{action.hazardous && <small>위험 작업 · 관리자 승인 필수</small>}</div></li>)}</ol>
            <div className="approval-bar"><button className="secondary">수정 후 승인</button><button className="danger-ghost">반려</button><button className="primary" onClick={approve}><ShieldCheck size={17} /> 승인 및 티켓 생성</button></div>
          </>
        )}
      </section>
    </div>
  );
}

function EquipmentPage({ equipment }: { equipment: Equipment[] }) {
  return <div className="card-grid">{equipment.map((item) => <article className="equipment-card" key={item.id}><div className="machine-icon"><Factory /></div><span className={`status-label ${item.status}`}>{item.status}</span><h3>{item.name}</h3><p>{item.line}</p><dl><div><dt>설비 ID</dt><dd>{item.id}</dd></div><div><dt>모델</dt><dd>{item.model}</dd></div><div><dt>최근 신호</dt><dd>{new Date(item.last_seen_at).toLocaleTimeString("ko-KR")}</dd></div></dl><button className="text-button">설비 상세 보기 <ChevronRight size={16} /></button></article>)}</div>;
}

function WorkOrdersPage({ workOrders, role, refresh, setNotice }: {
  workOrders: WorkOrder[]; role: string; refresh: () => Promise<void>; setNotice: (value: string) => void;
}) {
  const complete = async (order: WorkOrder) => {
    try {
      await api(`/api/v1/work-orders/${order.id}/complete`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ completed_items: order.checklist, photo_keys: ["local/evidence/photo-001.jpg"], field_note: "체크리스트 수행 및 시험 가동 완료", actual_cause: "베어링 윤활 불량", recovery_confirmed: true }),
      });
      await refresh();
      setNotice("현장 작업과 정상 복구 확인이 완료되었습니다.");
    } catch (error) { setNotice(String(error)); }
  };
  return <div className="work-list">{workOrders.length === 0 ? <EmptyState title="생성된 작업 티켓이 없습니다" /> : workOrders.map((order) => <article className="panel work-card" key={order.id}><div><span className={`status-label ${order.status}`}>{order.status}</span><h3>작업 티켓 #{order.id.slice(0, 8)}</h3><p>장애 #{order.incident_id.slice(0, 8)}</p></div><ul>{order.checklist.map((item) => <li key={item}><CheckCircle2 size={17} /> {item}</li>)}</ul>{role === "field_worker" && order.status !== "resolved" && <button className="primary" onClick={() => complete(order)}><Wrench size={17} /> 작업 완료 등록</button>}</article>)}</div>;
}

function DocumentsPage({ setNotice }: { setNotice: (value: string) => void }) {
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<KnowledgeHit[]>([]);
  const upload = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      await api("/api/v1/documents", { method: "POST", body: form });
      event.currentTarget.reset();
      setNotice("문서가 저장되었으며 색인 대기열에 등록되었습니다.");
    } catch (error) { setNotice(String(error)); }
  };
  const search = async () => {
    try { setHits(await api(`/api/v1/documents/search?q=${encodeURIComponent(query)}`)); }
    catch (error) { setNotice(String(error)); }
  };
  return <div className="documents-grid"><section className="panel"><PanelHeader title="문서 등록" subtitle="정비 매뉴얼과 과거 장애 사례를 등록합니다." /><form className="upload-form" onSubmit={upload}><div className="dropzone"><Upload /><strong>파일 선택</strong><p>TXT, MD, CSV, JSON 및 Bedrock 지원 문서</p><input type="file" name="file" required /></div><select name="document_type"><option value="manual">정비 매뉴얼</option><option value="incident_case">과거 장애 사례</option><option value="procedure">작업 절차서</option></select><button className="primary wide">문서 등록</button></form></section><section className="panel"><PanelHeader title="지식 검색" subtitle="분석에 사용될 근거 청크를 확인합니다." /><div className="search-row"><Search /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="예: 베어링 온도 상승" onKeyDown={(event) => event.key === "Enter" && search()} /><button onClick={search}>검색</button></div><div className="search-results">{hits.map((hit) => <article key={hit.location}><span>{Math.round(hit.score * 100)}% 일치</span><p>{hit.content}</p><small>{hit.location}</small></article>)}</div></section></div>;
}

function MetricsPage({ metrics }: { metrics: Metrics }) {
  const values = [
    { label: "원인 분석 정확도", value: metrics.cause_accuracy_average, color: "#2dd4bf" },
    { label: "조치안 유용성", value: metrics.action_usefulness_average, color: "#60a5fa" },
  ];
  return <><section className="kpi-grid metrics-kpis"><Kpi icon={Bot} label="평가 완료" value={metrics.analysis_count} unit="건" trend="누적 현장 평가" tone="violet" /><Kpi icon={ShieldCheck} label="전문가 검토율" value={Math.round(metrics.expert_review_rate * 100)} unit="%" trend="지속 개선 대상" tone="amber" /></section><section className="panel"><PanelHeader title="AI 품질 지표" subtitle="현장 피드백을 기반으로 산출됩니다." /><div className="quality-bars">{values.map((item) => <div key={item.label}><span>{item.label}</span><div><i style={{ width: `${(item.value / 5) * 100}%`, background: item.color }} /></div><strong>{item.value.toFixed(1)} / 5.0</strong></div>)}</div><div className="policy-banner"><ShieldCheck /><div><strong>Human-in-the-loop 정책 활성화</strong><p>고위험 조치안은 관리자의 승인 전까지 실행할 수 없습니다.</p></div></div></section></>;
}

function IncidentTable({ incidents, onIncident }: { incidents: Incident[]; onIncident: (incident: Incident) => void }) {
  if (!incidents.length) return <div className="table-empty">감지된 장애가 없습니다.</div>;
  return <div className="table-wrap"><table><thead><tr><th>위험도</th><th>설비</th><th>오류 코드</th><th>측정값</th><th>상태</th><th>감지 시각</th><th /></tr></thead><tbody>{incidents.map((incident) => <tr key={incident.id}><td><span className={`severity ${incident.severity}`}>{incident.severity}</span></td><td><strong>{incident.equipment_id}</strong></td><td>{incident.payload.error_code}</td><td>{incident.payload.measured_value} <small>/ {incident.payload.threshold}</small></td><td><span className="status-label">{statusLabel(incident.status)}</span></td><td>{new Date(incident.detected_at).toLocaleString("ko-KR")}</td><td><button className="icon-button" onClick={() => onIncident(incident)}><ChevronRight /></button></td></tr>)}</tbody></table></div>;
}

function Kpi({ icon: Icon, label, value, unit = "", trend, tone }: { icon: typeof Activity; label: string; value: number | string; unit?: string; trend: string; tone: string }) {
  return <article className="kpi-card"><div className={`kpi-icon ${tone}`}><Icon /></div><div><p>{label}</p><strong>{value}<small>{unit}</small></strong><span>{trend}</span></div></article>;
}

function PanelHeader({ title, subtitle }: { title: string; subtitle: string }) {
  return <div className="panel-header"><h3>{title}</h3><p>{subtitle}</p></div>;
}

function EmptyState({ title, onClick }: { title: string; onClick?: () => void }) {
  return <div className="panel empty-state"><ClipboardCheck /><h3>{title}</h3>{onClick && <button className="secondary" onClick={onClick}>목록으로 이동</button>}</div>;
}

function pageTitle(page: Page) {
  return navItems.find((item) => item.id === page)?.label ?? "장애 상세 및 AI 분석";
}

function roleLabel(role: string) {
  return role === "field_worker" ? "현장 작업자" : role === "system_admin" ? "시스템 관리자" : "운영 관리자";
}

function statusLabel(status: string) {
  const labels: Record<string, string> = { detected: "감지", analyzing: "분석 중", review_required: "검토 필요", approved: "승인", in_progress: "작업 중", resolved: "해결" };
  return labels[status] ?? status;
}

export default App;
