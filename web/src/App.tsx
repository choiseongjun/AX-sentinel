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
  UserCheck,
  Wrench,
  X,
} from "lucide-react";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import {
  beginSignIn,
  authProviderName,
  getAccessToken,
  isOidcEnabled,
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
  | "expert-reviews"
  | "work-orders"
  | "documents"
  | "metrics";

type Incident = {
  id: string;
  equipment_id: string;
  status: string;
  severity: string;
  detected_at: string;
  source?: string;
  telemetry_id?: string | null;
  payload: {
    sensor_type: string;
    measured_value: number;
    threshold: number;
    error_code: string;
    log_excerpt: string;
  };
};

function mergeIncidents(current: Incident[], incoming: Incident[]) {
  const incidentsById = new Map(current.map((incident) => [incident.id, incident]));
  incoming.forEach((incident) => incidentsById.set(incident.id, incident));
  return [...incidentsById.values()]
    .sort((left, right) => Date.parse(right.detected_at) - Date.parse(left.detected_at));
}

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
  audit?: {
    ai_provider: string;
    model_id: string;
    prompt_version: string;
    prompt_hash: string;
    rag_provider: string;
    document_versions: Record<string, string>;
    guardrail_action: string;
    request_id?: string | null;
    input_tokens?: number | null;
    output_tokens?: number | null;
  };
};

type ExpertReview = {
  id: string;
  analysis_id: string;
  incident_id: string;
  status: "pending" | "assigned" | "completed" | "dismissed";
  reasons: string[];
  risk_level: string;
  confidence: number;
  assignee_id?: string | null;
  resolution_note?: string | null;
  created_at: string;
  updated_at: string;
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
  approval_rate: number;
  cause_candidate_accuracy: number;
  document_hit_rate: number;
  resolution_time_reduction: number;
  evaluation_case_count: number;
};

type EvaluationRun = {
  id: string;
  case_count: number;
  cause_candidate_accuracy: number;
  document_hit_rate: number;
  resolution_time_reduction: number;
  created_at: string;
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
  { id: "expert-reviews" as Page, label: "전문가 검토함", icon: UserCheck },
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
          <p>
            {isOidcEnabled()
              ? `${authProviderName()} 계정으로 안전하게 로그인하세요.`
              : "로컬 개발 환경의 사용자 역할을 선택하세요."}
          </p>
          {!isOidcEnabled() && (
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
            onClick={() => isOidcEnabled() ? beginSignIn() : onLogin(role)}
          >
            {isOidcEnabled() ? `${authProviderName()}로 로그인` : "로컬 콘솔 시작"} <ChevronRight size={18} />
          </button>
          <div className="security-note">
            <ShieldCheck size={16} />
            {isOidcEnabled()
              ? `${authProviderName()} OIDC로 인증합니다.`
              : "로컬 역할 시뮬레이션 모드입니다."}
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
  const [expertReviews, setExpertReviews] = useState<ExpertReview[]>([]);
  const [metrics, setMetrics] = useState<Metrics>({
    analysis_count: 0,
    expert_review_rate: 0,
    cause_accuracy_average: 0,
    action_usefulness_average: 0,
    approval_rate: 0,
    cause_candidate_accuracy: 0,
    document_hit_rate: 0,
    resolution_time_reduction: 0,
    evaluation_case_count: 0,
  });
  const [selectedIncident, setSelectedIncident] = useState<Incident | null>(null);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [notice, setNotice] = useState("");
  const [authLoading, setAuthLoading] = useState(isOidcEnabled());

  useEffect(() => {
    if (!isOidcEnabled()) return;
    restoreUser()
      .then((user) => user && setRole(roleFromUser(user)))
      .catch((error) => setNotice(String(error)))
      .finally(() => setAuthLoading(false));
  }, []);

  const refresh = useCallback(async () => {
    const [incidentData, equipmentData, orderData, reviewData, metricData] = await Promise.all([
      api<Incident[]>("/api/v1/incidents"),
      api<Equipment[]>("/api/v1/equipment"),
      api<WorkOrder[]>("/api/v1/work-orders"),
      api<ExpertReview[]>("/api/v1/expert-reviews"),
      api<Metrics>("/api/v1/metrics/summary"),
    ]);
    setIncidents((current) => mergeIncidents(current, incidentData));
    setEquipment(equipmentData);
    setWorkOrders(orderData);
    setExpertReviews(reviewData);
    setMetrics(metricData);
  }, []);

  useEffect(() => {
    if (role) refresh().catch((error) => setNotice(error.message));
  }, [role, refresh]);

  useEffect(() => {
    if (!role) return;

    let disposed = false;
    let socket: WebSocket | undefined;
    let reconnectTimer: number | undefined;

    const connect = async () => {
      const token = await getAccessToken();
      if (disposed) return;
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const url = `${protocol}//${window.location.host}/api/v1/incidents/ws`;
      socket = token
        ? new WebSocket(url, ["access-token", token])
        : new WebSocket(url);
      socket.onmessage = (event) => {
        const incident = JSON.parse(event.data) as Incident;
        setIncidents((current) => mergeIncidents(current, [incident]));
        if (incident.status === "detected") {
          setNotice(`${incident.equipment_id} 자동 장애가 감지되었습니다.`);
        }
      };
      socket.onerror = () => socket?.close();
      socket.onclose = () => {
        if (!disposed) reconnectTimer = window.setTimeout(connect, 1500);
      };
    };

    connect().catch((error) => setNotice(`장애 스트림 연결 실패: ${String(error)}`));
    return () => {
      disposed = true;
      if (reconnectTimer) window.clearTimeout(reconnectTimer);
      if (socket) {
        socket.onclose = null;
        socket.close();
      }
    };
  }, [role]);

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
              {item.id === "expert-reviews" && expertReviews.filter((review) => review.status === "pending" || review.status === "assigned").length > 0 && (
                <span className="nav-badge">{expertReviews.filter((review) => review.status === "pending" || review.status === "assigned").length}</span>
              )}
            </button>
          ))}
        </nav>
        <div className="system-card">
          <div><span className="status-dot" /> 시스템 정상</div>
          <small>7개 서비스 연결됨</small>
        </div>
        <button className="user-card" onClick={() => isOidcEnabled() ? signOut() : setRole(null)}>
          <span className="avatar">{role === "field_worker" ? "현" : role === "system_admin" ? "시" : "운"}</span>
          <span><strong>{roleLabel(role)}</strong><small>{isOidcEnabled() ? "인증 사용자" : "로컬 사용자"}</small></span>
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
              role={role}
              refresh={refresh}
              setNotice={setNotice}
            />
          )}
          {page === "analysis" && !selectedIncident && <EmptyState title="분석할 장애를 선택하세요" onClick={() => setPage("incidents")} />}
          {page === "expert-reviews" && <ExpertReviewsPage reviews={expertReviews} refresh={refresh} setNotice={setNotice} />}
          {page === "work-orders" && <WorkOrdersPage workOrders={workOrders} role={role} refresh={refresh} setNotice={setNotice} />}
          {page === "documents" && <DocumentsPage role={role} setNotice={setNotice} />}
          {page === "metrics" && <MetricsPage metrics={metrics} refresh={refresh} setNotice={setNotice} />}
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

function mergeTelemetry(current: Telemetry[], incoming: Telemetry[]) {
  const recordsById = new Map(current.map((record) => [record.id, record]));
  incoming.forEach((record) => recordsById.set(record.id, record));
  return [...recordsById.values()]
    .sort((left, right) => Date.parse(right.received_at) - Date.parse(left.received_at))
    .slice(0, 100);
}

function LiveDataPage({ setNotice }: { setNotice: (value: string) => void }) {
  const [records, setRecords] = useState<Telemetry[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [connected, setConnected] = useState(false);

  const loadTelemetry = useCallback(async () => {
    try {
      const data = await api<Telemetry[]>("/api/v1/telemetry?limit=100");
      setRecords((current) => mergeTelemetry(current, data));
    } catch (error) {
      setNotice(`초기 실시간 데이터 조회 실패: ${String(error)}`);
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
  }, []);

  useEffect(() => {
    loadTelemetry();
  }, [loadTelemetry]);

  useEffect(() => {
    let disposed = false;
    let socket: WebSocket | undefined;
    let reconnectTimer: number | undefined;

    const connect = async () => {
      const token = await getAccessToken();
      if (disposed) return;

      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const url = `${protocol}//${window.location.host}/api/v1/telemetry/ws`;
      socket = token
        ? new WebSocket(url, ["access-token", token])
        : new WebSocket(url);

      socket.onopen = () => setConnected(true);
      socket.onmessage = (event) => {
        try {
          const telemetry = JSON.parse(event.data) as Telemetry;
          setRecords((current) => mergeTelemetry(current, [telemetry]));
        } catch (error) {
          setNotice(`WebSocket 메시지 처리 실패: ${String(error)}`);
        }
      };
      socket.onerror = () => socket?.close();
      socket.onclose = () => {
        setConnected(false);
        if (!disposed) reconnectTimer = window.setTimeout(connect, 1500);
      };
    };

    connect().catch((error) => {
      setConnected(false);
      setNotice(`WebSocket 연결 실패: ${String(error)}`);
    });

    return () => {
      disposed = true;
      if (reconnectTimer) window.clearTimeout(reconnectTimer);
      if (socket) {
        socket.onclose = null;
        socket.close();
      }
    };
  }, [setNotice]);

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
            <div><h3>센서 수신 스트림</h3><p>WebSocket으로 데이터를 즉시 수신합니다.</p></div>
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
        <Kpi icon={Radio} label="연결 상태" value={connected ? "ONLINE" : "OFFLINE"} trend="WebSocket / Incident service" tone={connected ? "green" : "red"} />
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
  const activeIncidents = incidents.filter((item) => item.status !== "resolved");
  const critical = activeIncidents.filter((item) => item.severity === "critical").length;
  return (
    <>
      <div className="hero-strip">
        <div><p className="eyebrow">PLANT STATUS</p><h3>오늘의 설비 운영 상태</h3><p>AI가 현장 신호를 지속적으로 감시하고 있습니다.</p></div>
        <div className="hero-score"><Gauge /><strong>92</strong><span>운영 건전성</span></div>
      </div>
      <section className="kpi-grid">
        <Kpi icon={Factory} label="연결 설비" value={equipment.length} unit="대" trend="정상 연결" tone="blue" />
        <Kpi icon={AlertTriangle} label="활성 장애" value={activeIncidents.length} unit="건" trend={`${critical}건 긴급`} tone="red" />
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

function AnalysisPage({ incident, analysis, setAnalysis, role, refresh, setNotice }: {
  incident: Incident; analysis: Analysis | null; setAnalysis: (value: Analysis) => void;
  role: string; refresh: () => Promise<void>; setNotice: (value: string) => void;
}) {
  const [loading, setLoading] = useState(false);
  const canManage = role === "operator_manager" || role === "system_admin";
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
  const decide = async (decision: "approve" | "approve_with_changes" | "reject") => {
    if (!analysis) return;
    try {
      const checklist = analysis.recommended_actions.map((item) => item.instruction);
      if (decision === "approve_with_changes") {
        checklist.unshift("관리자가 수정한 안전 조건과 작업 범위를 현장에서 재확인");
      }
      await api<WorkOrder | Record<string, unknown>>("/api/v1/approvals", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          analysis_id: analysis.id,
          incident_id: incident.id,
          decision,
          reviewer_id: "local-manager",
          comment: decision === "reject"
            ? "분석 근거 또는 조치 계획 보완 필요"
            : decision === "approve_with_changes"
              ? "안전 조건을 보강하여 수정 승인"
              : "분석 근거와 안전 절차 확인 후 승인",
          checklist,
        }),
      });
      if (decision === "reject") {
        setNotice("조치안이 반려되었습니다. 전문가 검토와 재분석이 필요합니다.");
        return;
      }
      await api(`/api/v1/incidents/${incident.id}/status`, {
        method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status: "approved" }),
      });
      await refresh();
      setNotice(decision === "approve_with_changes"
        ? "수정 조치안이 승인되어 작업 티켓이 생성되었습니다."
        : "조치안이 승인되어 작업 티켓이 생성되었습니다.");
    } catch (error) { setNotice(String(error)); }
  };
  return (
    <div className="analysis-layout">
      <section className="panel">
        <PanelHeader title={`장애 ${incident.id.slice(0, 8)}`} subtitle={`${incident.equipment_id} · ${incident.payload.error_code}`} />
        <div className="sensor-reading"><span>{incident.payload.sensor_type}</span><strong>{incident.payload.measured_value}</strong><small>임계값 {incident.payload.threshold}</small></div>
        <div className="log-box">{incident.payload.log_excerpt}</div>
        <button className="primary wide" onClick={runAnalysis} disabled={loading || !canManage}>
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
            {analysis.audit && (
              <>
                <h4>분석 감사 정보</h4>
                <dl className="audit-grid">
                  <div><dt>모델</dt><dd>{analysis.audit.ai_provider} / {analysis.audit.model_id}</dd></div>
                  <div><dt>프롬프트</dt><dd>{analysis.audit.prompt_version}</dd></div>
                  <div><dt>검색 엔진</dt><dd>{analysis.audit.rag_provider}</dd></div>
                  <div><dt>Guardrail</dt><dd>{analysis.audit.guardrail_action}</dd></div>
                  <div><dt>문서 버전</dt><dd>{Object.keys(analysis.audit.document_versions).length || 0}개</dd></div>
                  <div><dt>토큰</dt><dd>{analysis.audit.input_tokens ?? "-"} / {analysis.audit.output_tokens ?? "-"}</dd></div>
                </dl>
              </>
            )}
            {canManage && <div className="approval-bar"><button className="secondary" onClick={() => decide("approve_with_changes")}>수정 후 승인</button><button className="danger-ghost" onClick={() => decide("reject")}>반려</button><button className="primary" onClick={() => decide("approve")}><ShieldCheck size={17} /> 승인 및 티켓 생성</button></div>}
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
  return <div className="work-list">{workOrders.length === 0
    ? <EmptyState title="생성된 작업 티켓이 없습니다" />
    : workOrders.map((order) => (
      <WorkOrderCard
        key={order.id}
        order={order}
        editable={role === "field_worker" || role === "system_admin"}
        refresh={refresh}
        setNotice={setNotice}
      />
    ))}</div>;
}

function ExpertReviewsPage({ reviews, refresh, setNotice }: {
  reviews: ExpertReview[];
  refresh: () => Promise<void>;
  setNotice: (value: string) => void;
}) {
  const active = reviews.filter((review) => review.status === "pending" || review.status === "assigned");
  const closed = reviews.filter((review) => review.status === "completed" || review.status === "dismissed");
  return (
    <div className="review-sections">
      <section>
        <PanelHeader title="검토 대기 큐" subtitle="낮은 신뢰도, 근거 부족, 고위험 분석을 전문가에게 배정합니다." />
        <div className="review-grid">
          {active.length === 0
            ? <EmptyState title="검토 대기 중인 분석이 없습니다" />
            : active.map((review) => <ExpertReviewCard key={review.id} review={review} refresh={refresh} setNotice={setNotice} />)}
        </div>
      </section>
      {closed.length > 0 && (
        <section>
          <PanelHeader title="처리 이력" subtitle="완료 또는 제외된 전문가 검토 기록입니다." />
          <div className="review-grid closed">
            {closed.map((review) => <ExpertReviewCard key={review.id} review={review} refresh={refresh} setNotice={setNotice} />)}
          </div>
        </section>
      )}
    </div>
  );
}

function ExpertReviewCard({ review, refresh, setNotice }: {
  review: ExpertReview;
  refresh: () => Promise<void>;
  setNotice: (value: string) => void;
}) {
  const [assignee, setAssignee] = useState(review.assignee_id ?? "expert-01");
  const [note, setNote] = useState(review.resolution_note ?? "");
  const update = async (payload: Record<string, string>) => {
    try {
      await api(`/api/v1/expert-reviews/${review.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      await refresh();
      setNotice("전문가 검토 상태가 저장되었습니다.");
    } catch (error) { setNotice(String(error)); }
  };
  const isClosed = review.status === "completed" || review.status === "dismissed";
  return (
    <article className="panel review-card">
      <div className="review-card-head">
        <div><span className={`status-label ${review.status}`}>{reviewStatusLabel(review.status)}</span><h3>분석 #{review.analysis_id.slice(0, 8)}</h3><p>장애 #{review.incident_id.slice(0, 8)}</p></div>
        <span className={`severity ${review.risk_level}`}>{review.risk_level.toUpperCase()}</span>
      </div>
      <div className="review-confidence"><span>AI 신뢰도</span><strong>{Math.round(review.confidence * 100)}%</strong></div>
      <ul className="review-reasons">{review.reasons.map((reason) => <li key={reason}><AlertTriangle size={14} /> {reason}</li>)}</ul>
      {isClosed ? (
        <div className="review-resolution"><strong>{review.assignee_id ?? "미배정"}</strong><p>{review.resolution_note || "처리 메모 없음"}</p></div>
      ) : (
        <div className="review-form">
          <label>담당 전문가<input value={assignee} onChange={(event) => setAssignee(event.target.value)} /></label>
          <label>검토 메모<textarea value={note} onChange={(event) => setNote(event.target.value)} placeholder="판단 근거와 후속 조치를 기록하세요." /></label>
          <div>
            <button className="secondary" onClick={() => update({ assignee_id: assignee, status: "assigned" })}>담당자 배정</button>
            <button className="danger-ghost" onClick={() => update({ status: "dismissed", resolution_note: note || "검토 대상에서 제외" })}>제외</button>
            <button className="primary" onClick={() => update({ assignee_id: assignee, status: "completed", resolution_note: note })} disabled={note.trim().length < 3}><UserCheck size={17} /> 검토 완료</button>
          </div>
        </div>
      )}
    </article>
  );
}

function WorkOrderCard({ order, editable, refresh, setNotice }: {
  order: WorkOrder;
  editable: boolean;
  refresh: () => Promise<void>;
  setNotice: (value: string) => void;
}) {
  const [completedItems, setCompletedItems] = useState<string[]>(order.completed_items);
  const [evidence, setEvidence] = useState<File | null>(null);
  const [fieldNote, setFieldNote] = useState("");
  const [actualCause, setActualCause] = useState("");
  const [recoveryConfirmed, setRecoveryConfirmed] = useState(false);
  const [causeAccuracy, setCauseAccuracy] = useState(4);
  const [actionUsefulness, setActionUsefulness] = useState(4);

  const toggleItem = (item: string) => {
    setCompletedItems((current) => current.includes(item)
      ? current.filter((value) => value !== item)
      : [...current, item]);
  };

  const complete = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    try {
      if (!evidence) throw new Error("현장 증적 사진을 선택하세요.");
      const form = new FormData();
      form.append("file", evidence);
      const uploaded = await api<{ key: string }>(
        `/api/v1/work-orders/${order.id}/evidence`,
        { method: "POST", body: form },
      );
      await api(`/api/v1/work-orders/${order.id}/complete`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          completed_items: completedItems,
          photo_keys: [uploaded.key],
          field_note: fieldNote,
          actual_cause: actualCause,
          recovery_confirmed: recoveryConfirmed,
        }),
      });
      await api("/api/v1/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          incident_id: order.incident_id,
          analysis_id: order.analysis_id,
          cause_accuracy: causeAccuracy,
          action_usefulness: actionUsefulness,
          actual_cause: actualCause,
          comment: fieldNote,
        }),
      });
      await refresh();
      setNotice("현장 작업과 정상 복구 확인이 완료되었습니다.");
    } catch (error) { setNotice(String(error)); }
  };

  return (
    <article className="panel work-card">
      <div><span className={`status-label ${order.status}`}>{order.status}</span><h3>작업 티켓 #{order.id.slice(0, 8)}</h3><p>장애 #{order.incident_id.slice(0, 8)}</p></div>
      <ul>{order.checklist.map((item) => <li key={item}>
        {editable && order.status !== "resolved"
          ? <input type="checkbox" checked={completedItems.includes(item)} onChange={() => toggleItem(item)} />
          : <CheckCircle2 size={17} />}
        {item}
      </li>)}</ul>
      {editable && order.status !== "resolved" && (
        <form className="work-completion-form" onSubmit={complete}>
          <label>현장 증적 사진<input type="file" accept="image/*" required onChange={(event) => setEvidence(event.target.files?.[0] ?? null)} /></label>
          <label>현장 메모<textarea required minLength={3} value={fieldNote} onChange={(event) => setFieldNote(event.target.value)} /></label>
          <label>실제 장애 원인<input required minLength={3} value={actualCause} onChange={(event) => setActualCause(event.target.value)} /></label>
          <label>AI 원인 정확도<select value={causeAccuracy} onChange={(event) => setCauseAccuracy(Number(event.target.value))}>{[1, 2, 3, 4, 5].map((score) => <option key={score} value={score}>{score}점</option>)}</select></label>
          <label>조치안 유용성<select value={actionUsefulness} onChange={(event) => setActionUsefulness(Number(event.target.value))}>{[1, 2, 3, 4, 5].map((score) => <option key={score} value={score}>{score}점</option>)}</select></label>
          <label className="recovery-check"><input type="checkbox" checked={recoveryConfirmed} onChange={(event) => setRecoveryConfirmed(event.target.checked)} /> 시험 가동 후 정상 복구 확인</label>
          <button className="primary" type="submit"><Wrench size={17} /> 작업 완료 등록</button>
        </form>
      )}
    </article>
  );
}

function DocumentsPage({ role, setNotice }: { role: string; setNotice: (value: string) => void }) {
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
  const canManage = role === "operator_manager" || role === "system_admin";
  return <div className="documents-grid"><section className="panel"><PanelHeader title="문서 등록" subtitle="정비 매뉴얼과 과거 장애 사례를 등록합니다." />{canManage ? <form className="upload-form" onSubmit={upload}><div className="dropzone"><Upload /><strong>파일 선택</strong><p>TXT, MD, CSV, JSON 및 Bedrock 지원 문서</p><input type="file" name="file" required /></div><select name="document_type"><option value="manual">정비 매뉴얼</option><option value="incident_case">과거 장애 사례</option><option value="procedure">작업 절차서</option></select><button className="primary wide">문서 등록</button></form> : <p className="table-empty">문서 등록 권한이 없습니다.</p>}</section><section className="panel"><PanelHeader title="지식 검색" subtitle="분석에 사용될 근거 청크를 확인합니다." /><div className="search-row"><Search /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="예: 베어링 온도 상승" onKeyDown={(event) => event.key === "Enter" && search()} /><button onClick={search}>검색</button></div><div className="search-results">{hits.map((hit) => <article key={hit.location}><span>{Math.round(hit.score * 100)}% 일치</span><p>{hit.content}</p><small>{hit.location}</small></article>)}</div></section></div>;
}

function MetricsPage({ metrics, refresh, setNotice }: {
  metrics: Metrics;
  refresh: () => Promise<void>;
  setNotice: (value: string) => void;
}) {
  const [running, setRunning] = useState(false);
  const [latestRun, setLatestRun] = useState<EvaluationRun | null>(null);
  const values = [
    { label: "원인 분석 정확도", value: metrics.cause_accuracy_average, color: "#2dd4bf" },
    { label: "조치안 유용성", value: metrics.action_usefulness_average, color: "#60a5fa" },
  ];
  const runEvaluation = async () => {
    setRunning(true);
    try {
      const result = await api<EvaluationRun>("/api/v1/evaluations/run", { method: "POST" });
      setLatestRun(result);
      await refresh();
      setNotice(`${result.case_count}개 정답 사례의 자동 평가를 완료했습니다.`);
    } catch (error) { setNotice(String(error)); } finally { setRunning(false); }
  };
  return (
    <>
      <section className="kpi-grid metrics-kpis">
        <Kpi icon={Bot} label="분석 이력" value={metrics.analysis_count} unit="건" trend="감사 가능한 누적 분석" tone="violet" />
        <Kpi icon={ShieldCheck} label="전문가 검토율" value={Math.round(metrics.expert_review_rate * 100)} unit="%" trend="Human-in-the-loop" tone="amber" />
        <Kpi icon={CheckCircle2} label="원인 후보 정확도" value={Math.round(metrics.cause_candidate_accuracy * 100)} unit="%" trend={`${metrics.evaluation_case_count}개 정답 사례`} tone="green" />
        <Kpi icon={FileSearch} label="문서 검색 적중률" value={Math.round(metrics.document_hit_rate * 100)} unit="%" trend="기대 문서 Top-K 적중" tone="blue" />
        <Kpi icon={Gauge} label="조치안 승인율" value={Math.round(metrics.approval_rate * 100)} unit="%" trend="승인·수정 승인 비율" tone="green" />
        <Kpi icon={Activity} label="해결 시간 감소율" value={Math.round(metrics.resolution_time_reduction * 100)} unit="%" trend="기준 대비 평균 감소" tone="blue" />
      </section>
      <section className="panel">
        <div className="panel-actions">
          <PanelHeader title="AI 자동 평가" subtitle="버전 고정 정답 데이터셋으로 분석과 검색 품질을 반복 측정합니다." />
          <button className="primary" onClick={runEvaluation} disabled={running || metrics.evaluation_case_count === 0}><Bot size={17} /> {running ? "평가 중..." : "평가 실행"}</button>
        </div>
        {latestRun && <p className="evaluation-result">최근 실행 #{latestRun.id.slice(0, 8)} · 원인 {Math.round(latestRun.cause_candidate_accuracy * 100)}% · 문서 {Math.round(latestRun.document_hit_rate * 100)}% · 시간 {Math.round(latestRun.resolution_time_reduction * 100)}%</p>}
        <div className="quality-bars">{values.map((item) => <div key={item.label}><span>{item.label}</span><div><i style={{ width: `${(item.value / 5) * 100}%`, background: item.color }} /></div><strong>{item.value.toFixed(1)} / 5.0</strong></div>)}</div>
        <div className="policy-banner"><ShieldCheck /><div><strong>Human-in-the-loop 정책 활성화</strong><p>고위험 조치안과 낮은 신뢰도 분석은 전문가 검토 후 관리자가 승인합니다.</p></div></div>
      </section>
    </>
  );
}

function IncidentTable({ incidents, onIncident }: { incidents: Incident[]; onIncident: (incident: Incident) => void }) {
  if (!incidents.length) return <div className="table-empty">감지된 장애가 없습니다.</div>;
  return <div className="table-wrap"><table><thead><tr><th>위험도</th><th>설비</th><th>감지 방식</th><th>오류 코드</th><th>측정값</th><th>상태</th><th>감지 시각</th><th /></tr></thead><tbody>{incidents.map((incident) => <tr key={incident.id}><td><span className={`severity ${incident.severity}`}>{incident.severity}</span></td><td><strong>{incident.equipment_id}</strong></td><td>{incident.source === "automatic" ? "자동 감지" : "수동 생성"}</td><td>{incident.payload.error_code}</td><td>{incident.payload.measured_value} <small>/ {incident.payload.threshold}</small></td><td><span className="status-label">{statusLabel(incident.status)}</span></td><td>{new Date(incident.detected_at).toLocaleString("ko-KR")}</td><td><button className="icon-button" onClick={() => onIncident(incident)}><ChevronRight /></button></td></tr>)}</tbody></table></div>;
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

function reviewStatusLabel(status: ExpertReview["status"]) {
  const labels: Record<ExpertReview["status"], string> = { pending: "검토 대기", assigned: "담당자 배정", completed: "검토 완료", dismissed: "제외" };
  return labels[status];
}

export default App;
