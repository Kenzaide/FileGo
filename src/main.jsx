import React, { useState, useEffect, useRef, useCallback, createContext, useContext } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter, useNavigate, useLocation, Navigate, Link } from 'react-router-dom';
import {
  LayoutDashboard, LibraryBig, FolderOpen, Send, Inbox, History, Activity, Settings, ShieldCheck, LogOut,
  Search, Upload, Download, FileText, FileImage, File, ChevronRight, Plus, Menu, X, Trash2, Edit3, Eye,
  ArrowUpRight, ArrowDownLeft, HardDrive, Cpu, MemoryStick, Wifi, Users, Lock, Globe, BookOpen,
  CheckCircle2, AlertCircle, Sun, Moon, RefreshCw, Shield, CloudUpload, FileUp, ChartNoAxesCombined,
} from 'lucide-react';
import { AreaChart, Area, CartesianGrid, XAxis, YAxis, Tooltip, ResponsiveContainer, BarChart, Bar } from 'recharts';
import './style.css';
import { api, request, login as apiLogin, register as apiRegister, restoreSession, logout as apiLogout, setUnauthorizedHandler, uploadRaw, reportClientTiming, startDownload, previewUrl } from './api.js';

const DEMO_MODE = import.meta.env.VITE_DEMO_MODE === 'true';

/* ------------------------------------------------------------------ helpers */

const fmt = (n) => (n >= 1e9 ? (n / 1e9).toFixed(1) + ' GB' : n >= 1e6 ? (n / 1e6).toFixed(2) + ' MB' : n >= 1e3 ? (n / 1e3).toFixed(1) + ' KB' : (n || 0) + ' B');
// Timestamps are stored in UTC; show the date in the viewer's own time zone.
const localDate = (iso) => (iso ? new Date(iso).toLocaleDateString('en-CA') : '');
const initials = (s) => (s || '?').split(' ').map((x) => x[0]).slice(0, 2).join('').toUpperCase();
const iconFor = (f) => (f.kind === 'PDF' ? <FileText /> : f.kind === 'PPTX' ? <FileImage /> : f.kind === 'DOCX' ? <FileText /> : ['PNG', 'JPG', 'JPEG', 'GIF', 'WEBP'].includes(f.kind) ? <FileImage /> : <File />);
const PREVIEWABLE = ['PDF', 'PNG', 'JPG', 'JPEG', 'GIF', 'WEBP'];
const IMAGE_KINDS = ['PNG', 'JPG', 'JPEG', 'GIF', 'WEBP'];

/* ------------------------------------------------------------------ app context */

const C = createContext(null);
const useApp = () => useContext(C);

function readTheme() {
  try { return localStorage.getItem('filego-theme') === 'dark' ? 'dark' : 'light'; } catch { return 'light'; }
}

function Provider({ children }) {
  const [user, setUser] = useState(null);
  const [meta, setMeta] = useState(null);
  const [booting, setBooting] = useState(true);
  const [theme, setThemeState] = useState(readTheme);
  const [version, setVersion] = useState(0); // bump() makes pages reload their data
  const [toastState, setToast] = useState(null);
  const timer = useRef(null);

  const toast = useCallback((msg, kind = 'ok') => {
    setToast({ msg, kind });
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setToast(null), kind === 'error' ? 5000 : 3200);
  }, []);
  const bump = useCallback(() => setVersion((v) => v + 1), []);
  const setTheme = (t) => {
    setThemeState(t);
    try { localStorage.setItem('filego-theme', t); } catch { /* private mode */ }
  };

  useEffect(() => {
    setUnauthorizedHandler(() => setUser(null));
    (async () => {
      try { setMeta(await api.get('/api/meta')); } catch { /* shown below */ }
      try { setUser(await restoreSession()); } catch { toast('Cannot reach the FileGo server.', 'error'); }
      setBooting(false);
    })();
  }, [toast]);

  const value = { user, setUser, meta, theme, setTheme, toast, version, bump, booting };
  return (
    <C.Provider value={value}>
      {children}
      {toastState && (
        <div className={'toast ' + (toastState.kind === 'error' ? 'error' : '')} role="status">
          {toastState.kind === 'error' ? <AlertCircle size={18} /> : <CheckCircle2 size={18} />}
          {toastState.msg}
        </div>
      )}
    </C.Provider>
  );
}

// Loads data from the API and reloads when the page asks (version) or deps change.
function useLoad(fn, deps = []) {
  const { toast, version } = useApp();
  const [state, setState] = useState({ data: null, loading: true, error: null });
  const fnRef = useRef(fn);
  fnRef.current = fn;
  useEffect(() => {
    let alive = true;
    setState((s) => ({ ...s, loading: true }));
    fnRef.current()
      .then((data) => alive && setState({ data, loading: false, error: null }))
      .catch((error) => {
        if (!alive) return;
        setState({ data: null, loading: false, error });
        toast(error.message, 'error');
      });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [version, ...deps]);
  return state;
}

function useDebounced(value, ms = 250) {
  const [v, setV] = useState(value);
  useEffect(() => { const t = setTimeout(() => setV(value), ms); return () => clearTimeout(t); }, [value, ms]);
  return v;
}

/* ------------------------------------------------------------------ small components */

function Button({ children, onClick, variant = 'primary', type = 'button', disabled = false, loading = false, ...props }) {
  return (
    <button type={type} className={'btn ' + variant} onClick={onClick} disabled={disabled || loading} aria-busy={loading} {...props}>
      {loading && <RefreshCw size={16} className="spin" aria-hidden="true" />}
      {children}
    </button>
  );
}

function Empty({ icon: Icon = FolderOpen, title = 'Nothing here yet', desc = 'Your items will appear here.' }) {
  return (
    <div className="empty"><Icon size={32} /><h3>{title}</h3><p>{desc}</p></div>
  );
}

const Loading = ({ text = 'Loading…' }) => <div className="empty"><RefreshCw size={26} className="spin" /><p>{text}</p></div>;
const Tag = ({ children, tone = '' }) => <span className={'tag ' + tone}>{children}</span>;

function Header({ title, subtitle, actions }) {
  return (
    <div className="page-header">
      <div><h1>{title}</h1><p>{subtitle}</p></div>
      {actions && <div className="header-actions">{actions}</div>}
    </div>
  );
}

function Stat({ label, value, Icon, foot }) {
  return (
    <div className="stat">
      <div className="stat-top"><span>{label}</span><div className="stat-icon"><Icon size={19} /></div></div>
      <strong>{value}</strong>
      <small>{foot}</small>
    </div>
  );
}

function Pager({ page, perPage, total, onPage }) {
  const pages = Math.max(1, Math.ceil(total / perPage));
  if (pages <= 1) return null;
  return (
    <div className="pager">
      <Button variant="secondary" disabled={page <= 1} onClick={() => onPage(page - 1)}>Previous</Button>
      <span>Page {page} of {pages}</span>
      <Button variant="secondary" disabled={page >= pages} onClick={() => onPage(page + 1)}>Next</Button>
    </div>
  );
}

function Modal({ title, subtitle, onClose, children, wide = false }) {
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={'modal' + (wide ? ' wide' : '')} role="dialog" aria-modal="true" aria-label={title}>
        <div className="modal-head">
          <div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div>
          <Button variant="icon" onClick={onClose} aria-label="Close"><X /></Button>
        </div>
        {children}
      </div>
    </div>
  );
}

function PreviewModal({ file, onClose }) {
  const isImage = IMAGE_KINDS.includes(file.kind);
  return (
    <Modal title={file.name} subtitle={`${file.kind} · ${fmt(file.size)}`} onClose={onClose} wide>
      <div className="preview-box">
        {isImage
          ? <img src={previewUrl(file.id)} alt={file.name} />
          : <iframe src={previewUrl(file.id)} title={file.name} />}
      </div>
    </Modal>
  );
}

// Starts a browser download and refreshes counters shortly after.
function useDownload() {
  const { toast, bump } = useApp();
  return async (id) => {
    try {
      await startDownload(id);
      toast('Download started');
      setTimeout(bump, 1500);
    } catch (e) { toast(e.message, 'error'); }
  };
}

function FileRow({ file }) {
  const download = useDownload();
  const [preview, setPreview] = useState(false);
  return (
    <div className="file-row">
      <div className={'file-icon ' + (file.kind || '').toLowerCase()}>{iconFor(file)}</div>
      <div className="file-main">
        <strong title={file.name}>{file.name}</strong>
        <span>{file.subject} · {fmt(file.size)} · {file.owner}</span>
      </div>
      <Tag>{file.category}</Tag>
      <div className="file-date">{localDate(file.createdAt)}</div>
      {file.previewable && <Button variant="icon" title="Preview" onClick={() => setPreview(true)} aria-label={'Preview ' + file.name}><Eye size={18} /></Button>}
      <Button variant="icon" title="Download file" onClick={() => download(file.id)} aria-label={'Download ' + file.name}><Download size={18} /></Button>
      {preview && <PreviewModal file={file} onClose={() => setPreview(false)} />}
    </div>
  );
}

/* ------------------------------------------------------------------ upload / send */

function UploadModal({ onClose, mode = 'public', recipientId = '' }) {
  const { meta, toast, bump } = useApp();
  const subjects = meta?.subjects || [];
  const categories = meta?.categories || [];
  const maxMb = meta?.maxUploadMb || 100;
  const [file, setFile] = useState(null);
  const [subjectId, setSubjectId] = useState(subjects[0]?.id || '');
  const [category, setCategory] = useState(categories[0] || '');
  const [visibility, setVisibility] = useState(mode);
  const [recipient, setRecipient] = useState(recipientId);
  const [title, setTitle] = useState('');
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(null); // {loaded,total,seconds}
  const job = useRef(null);
  const users = useLoad(() => (visibility === 'direct' ? api.get('/api/users') : Promise.resolve({ items: [] })), [visibility]);

  const choose = (f) => {
    if (!f) return setFile(null);
    if (f.size > maxMb * 1024 * 1024) { toast(`That file is larger than the ${maxMb} MB limit.`, 'error'); return; }
    setFile(f);
  };

  const submit = async (e) => {
    e.preventDefault();
    if (!file) return toast('Choose a file first', 'error');
    if (visibility === 'direct' && !recipient) return toast('Select a recipient', 'error');
    const q = new URLSearchParams({ subject: subjectId, category });
    if (title.trim()) q.set('title', title.trim());
    let url;
    if (visibility === 'direct') { q.set('recipientId', recipient); url = '/api/transfers?' + q; }
    else { q.set('visibility', visibility); url = '/api/files?' + q; }
    setBusy(true);
    setProgress({ loaded: 0, total: file.size, seconds: 0 });
    try {
      job.current = uploadRaw(url, file, { onProgress: (loaded, total, seconds) => setProgress({ loaded, total, seconds }) });
      const { body, seconds } = await job.current;
      reportClientTiming(body?.logId, seconds);
      toast(visibility === 'direct' ? 'File sent to recipient' : 'File uploaded successfully');
      bump();
      onClose();
    } catch (err) {
      if (err.code !== 'cancelled') toast(err.message, 'error');
      setBusy(false);
      setProgress(null);
    }
  };

  const cancel = () => { if (busy && job.current) job.current.abort(); else onClose(); };
  const pct = progress && progress.total ? Math.min(100, Math.round((progress.loaded / progress.total) * 100)) : 0;
  const speed = progress && progress.seconds > 0 ? progress.loaded / 1e6 / progress.seconds : 0;
  const allowed = (meta?.allowedExtensions || []).map((e) => '.' + e).join(',');

  return (
    <Modal title={mode === 'direct' ? 'Send a file' : 'Upload academic material'} subtitle="Files are stored on the FileGo server and shared over your local network." onClose={cancel}>
      <form onSubmit={submit} className="form-stack">
        <label className="drop">
          <CloudUpload size={34} />
          <strong>{file ? file.name : 'Choose a file to upload'}</strong>
          <span>{file ? fmt(file.size) : `${(meta?.allowedExtensions || []).join(', ').toUpperCase()} · up to ${maxMb} MB`}</span>
          <input type="file" accept={allowed} disabled={busy} onChange={(e) => choose(e.target.files[0] || null)} />
        </label>
        <label>Display title
          <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Optional: defaults to filename" disabled={busy} />
        </label>
        <div className="two-col">
          <label>Subject
            <select value={subjectId} onChange={(e) => setSubjectId(e.target.value)} disabled={busy}>
              {subjects.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
            </select>
          </label>
          <label>Category
            <select value={category} onChange={(e) => setCategory(e.target.value)} disabled={busy}>
              {categories.map((s) => <option key={s}>{s}</option>)}
            </select>
          </label>
        </div>
        <label>Sharing
          <select value={visibility} onChange={(e) => setVisibility(e.target.value)} disabled={busy}>
            <option value="public">Shared Academic Library</option>
            <option value="private">Private — only me</option>
            <option value="direct">Direct share — specific student</option>
          </select>
        </label>
        {visibility === 'direct' && (
          <label>Recipient
            <select value={recipient} onChange={(e) => setRecipient(e.target.value)} required disabled={busy}>
              <option value="">Choose student</option>
              {(users.data?.items || []).map((u) => <option key={u.id} value={u.id}>{u.name} (@{u.username})</option>)}
            </select>
          </label>
        )}
        {progress && (
          <div className="progress-wrap" aria-live="polite">
            <div className="progress"><div style={{ width: pct + '%' }} /></div>
            <small>{pct}% · {fmt(progress.loaded)} of {fmt(progress.total)}{speed ? ` · ${speed.toFixed(2)} MB/s` : ''}</small>
          </div>
        )}
        <div className="modal-actions">
          <Button variant="secondary" onClick={cancel}>{busy ? 'Cancel upload' : 'Cancel'}</Button>
          <Button type="submit" loading={busy} disabled={!file}>
            <Upload size={17} />{busy ? 'Uploading…' : visibility === 'direct' ? 'Send file' : 'Upload file'}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

/* ------------------------------------------------------------------ shell */

const nav = [
  { title: 'Workspace', items: [['/dashboard', 'Dashboard', LayoutDashboard], ['/library', 'Academic Library', LibraryBig], ['/my-files', 'My Files', FolderOpen], ['/send', 'Send Files', Send], ['/inbox', 'Inbox', Inbox]] },
  { title: 'Insights', items: [['/history', 'Transfer History', History], ['/performance', 'Performance', Activity]] },
  { title: 'Account', items: [['/settings', 'Settings', Settings], ['/admin', 'Administration', ShieldCheck]] },
];

function Shell({ children }) {
  const { user, setUser, theme, setTheme, meta, version } = useApp();
  const loc = useLocation();
  const navigate = useNavigate();
  const [mobile, setMobile] = useState(false);
  const [upload, setUpload] = useState(false);
  const [unread, setUnread] = useState(0);

  useEffect(() => {
    if (!user) return undefined;
    let alive = true;
    const poll = () => api.get('/api/transfers/unread-count').then((r) => alive && setUnread(r.count)).catch(() => {});
    poll();
    const t = setInterval(poll, 30000);
    return () => { alive = false; clearInterval(t); };
  }, [user, loc.pathname, version]);

  if (!user) return <Navigate to="/login" replace />;
  const signOut = async () => { try { await apiLogout(); } catch { /* cookie is cleared anyway */ } setUser(null); navigate('/login'); };

  return (
    <div className={'app ' + (theme === 'dark' ? 'dark' : '')}>
      <aside className={'sidebar ' + (mobile ? 'shown' : '')}>
        <div className="brand">
          <div className="brand-mark"><img src="/filego-logo.png" alt="" /></div>
          <div><strong>FileGo</strong><small>Academic Sharing Hub</small></div>
          <button className="mobile-close" onClick={() => setMobile(false)}><X /></button>
        </div>
        <div className="side-scroll">
          <button className="side-upload" onClick={() => { setUpload(true); setMobile(false); }}><Plus size={18} /> Upload a file</button>
          {nav.map((group) => (
            <div className="nav-group" key={group.title}>
              <div className="nav-label">{group.title}</div>
              {group.items.filter(([path]) => path !== '/admin' || user.role === 'admin').map(([path, label, Icon]) => (
                <Link key={path} to={path} onClick={() => setMobile(false)} className={'nav-link ' + (loc.pathname === path ? 'active' : '')}>
                  <Icon size={18} />{label}
                  {path === '/inbox' && unread > 0 && <span className="nav-dot" title={unread + ' new'} />}
                </Link>
              ))}
            </div>
          ))}
        </div>
        <div className="side-foot">
          <div className="local-status"><span className="online-dot" /> Connected to server</div>
          <div className="profile-mini">
            <div className="avatar">{initials(user.name)}</div>
            <div><strong>{user.name}</strong><small>{user.role === 'admin' ? 'Administrator' : 'Student'}</small></div>
            <button title="Logout" onClick={signOut}><LogOut size={17} /></button>
          </div>
        </div>
      </aside>
      {mobile && <div className="mobile-overlay" onClick={() => setMobile(false)} />}
      <div className="main">
        <header className="topbar">
          <button className="hamburger" onClick={() => setMobile(true)}><Menu /></button>
          <div className="breadcrumb">Workspace <ChevronRight size={15} /> <strong>{nav.flatMap((g) => g.items).find(([p]) => p === loc.pathname)?.[1] || 'FileGo'}</strong></div>
          <div className="top-actions">
            <span className="connection"><Wifi size={15} /> {meta?.serverMode === 'stream' ? 'Streaming server' : 'LAN server'}</span>
            <button className="round" title="Toggle theme" onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}>{theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}</button>
            <div className="avatar top-avatar">{initials(user.name)}</div>
          </div>
        </header>
        <main className="content">
          {user.mustChangePassword && (
            <div className="notice"><AlertCircle size={18} /><div><strong>Choose a new password</strong><p>An administrator reset your password. Please set a new one in <Link to="/settings">Settings</Link>.</p></div></div>
          )}
          {children}
        </main>
      </div>
      {upload && <UploadModal onClose={() => setUpload(false)} />}
    </div>
  );
}

/* ------------------------------------------------------------------ pages */

function Dashboard() {
  const { user } = useApp();
  const navigate = useNavigate();
  const [upload, setUpload] = useState(false);
  const stats = useLoad(() => api.get('/api/stats/me'));
  const recent = useLoad(() => api.get('/api/files', { scope: 'library', perPage: 5 }));
  const s = stats.data;
  const items = recent.data?.items || [];
  return (
    <>
      <Header title={'Your academic workspace, ' + user.name.split(' ')[0]} subtitle="Manage materials, find reviewers, and share files with classmates." actions={<Button onClick={() => setUpload(true)}><Plus size={17} /> Upload material</Button>} />
      <div className="hero">
        <div>
          <h2>All your academic files, <span>one shared workspace.</span></h2>
          <p>Find reviewers, organize study materials, and send files directly to classmates.</p>
          <div className="hero-actions">
            <Button variant="white" onClick={() => navigate('/library')}><BookOpen size={17} /> Browse reviewers</Button>
            <Button variant="ghost-light" onClick={() => navigate('/send')}><Send size={17} /> Send a file</Button>
          </div>
        </div>
        <div className="hero-preview" aria-hidden="true">
          <div className="preview-caption">Recently shared</div>
          {items.slice(0, 2).map((f) => (
            <div className="preview-file" key={f.id}><FileText size={20} /><div><strong>{f.name}</strong><small>{f.category} · {f.kind}</small></div><CheckCircle2 size={17} /></div>
          ))}
          <div className="preview-footer"><FolderOpen size={16} /> Browse course materials <ChevronRight size={16} /></div>
        </div>
      </div>
      <div className="stats">
        <Stat label="My files" value={s ? s.myFiles : '—'} Icon={FolderOpen} foot="Materials you own" />
        <Stat label="Library materials" value={recent.data ? recent.data.total : '—'} Icon={LibraryBig} foot="Available to everyone" />
        <Stat label="Received files" value={s ? s.received : '—'} Icon={Inbox} foot="Directly shared with you" />
        <Stat label="Downloads" value={s ? s.downloads : '—'} Icon={Download} foot="Times others downloaded your files" />
      </div>
      <div className="dash-grid">
        <section className="panel">
          <div className="panel-title"><div><h3>Recent academic materials</h3></div><Link to="/library" className="text-link">View all <ChevronRight size={16} /></Link></div>
          <div className="dashboard-recent-scroll" role="region" aria-label="Recent academic materials" tabIndex={0}>
            {recent.loading ? <Loading /> : items.length ? items.map((f) => <FileRow key={f.id} file={f} />) : <Empty title="The library is empty" desc="Be the first to share a material." />}
          </div>
        </section>
        <section className="panel">
          <div className="panel-title"><div><h3>Quick actions</h3></div></div>
          <div className="quick-grid">
            {[[LibraryBig, 'Browse reviewers', '/library'], [Send, 'Send a file', '/send'], [Inbox, 'My inbox', '/inbox'], [Activity, 'Performance', '/performance']].map(([Icon, label, path]) => (
              <button className="quick" key={path} onClick={() => navigate(path)}><Icon size={23} /><span>{label}</span><ChevronRight size={16} /></button>
            ))}
          </div>
        </section>
      </div>
      {upload && <UploadModal onClose={() => setUpload(false)} />}
    </>
  );
}

function Library() {
  const { meta } = useApp();
  const [search, setSearch] = useState('');
  const [subject, setSubject] = useState('');
  const [category, setCategory] = useState('');
  const [page, setPage] = useState(1);
  const [upload, setUpload] = useState(false);
  const q = useDebounced(search);
  useEffect(() => setPage(1), [q, subject, category]);
  const res = useLoad(() => api.get('/api/files', { scope: 'library', q, subject, category, page, perPage: 20 }), [q, subject, category, page]);
  const items = res.data?.items || [];
  const total = res.data?.total || 0;
  return (
    <>
      <Header title="Academic Library" subtitle="Discover reviewers, notes, presentations, and resources shared by students." actions={<Button onClick={() => setUpload(true)}><Plus size={17} /> Contribute material</Button>} />
      <div className="panel">
        <div className="filters">
          <div className="search"><Search size={18} /><input placeholder="Search by title, subject, or uploader..." value={search} onChange={(e) => setSearch(e.target.value)} /></div>
          <select value={subject} onChange={(e) => setSubject(e.target.value)} aria-label="Subject">
            <option value="">All subjects</option>
            {(meta?.subjects || []).map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
          </select>
          <select value={category} onChange={(e) => setCategory(e.target.value)} aria-label="Material type">
            <option value="">All types</option>
            {(meta?.categories || []).map((s) => <option key={s}>{s}</option>)}
          </select>
        </div>
        <div className="section-caption">{res.loading ? 'Searching…' : `${total} material${total !== 1 ? 's' : ''} found`}</div>
        {res.loading && !items.length ? <Loading /> : items.length ? items.map((f) => <FileRow key={f.id} file={f} />) : <Empty title="No matching materials" desc="Try changing your search or filters." />}
        <Pager page={page} perPage={20} total={total} onPage={setPage} />
      </div>
      {upload && <UploadModal onClose={() => setUpload(false)} />}
    </>
  );
}

function EditModal({ file, onClose }) {
  const { meta, toast, bump } = useApp();
  const [name, setName] = useState(file.name);
  const [subjectId, setSubjectId] = useState(file.subjectId);
  const [category, setCategory] = useState(file.category);
  const [visibility, setVisibility] = useState(file.visibility);
  const [busy, setBusy] = useState(false);
  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      await api.patch('/api/files/' + file.id, { name, subjectId, category, visibility });
      toast('File updated');
      bump();
      onClose();
    } catch (err) { toast(err.message, 'error'); setBusy(false); }
  };
  return (
    <Modal title="Edit file" subtitle={file.originalName} onClose={onClose}>
      <form className="form-stack" onSubmit={submit}>
        <label>Display title<input required value={name} onChange={(e) => setName(e.target.value)} maxLength={255} /></label>
        <div className="two-col">
          <label>Subject
            <select value={subjectId} onChange={(e) => setSubjectId(e.target.value)}>{(meta?.subjects || []).map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}</select>
          </label>
          <label>Category
            <select value={category} onChange={(e) => setCategory(e.target.value)}>{(meta?.categories || []).map((s) => <option key={s}>{s}</option>)}</select>
          </label>
        </div>
        <label>Visibility
          <select value={visibility} onChange={(e) => setVisibility(e.target.value)}>
            <option value="public">Public — shown in the Academic Library</option>
            <option value="private">Private — only me (and people I sent it to)</option>
          </select>
        </label>
        <div className="modal-actions">
          <Button variant="secondary" onClick={onClose}>Cancel</Button>
          <Button type="submit" loading={busy}>Save changes</Button>
        </div>
      </form>
    </Modal>
  );
}

function MyFiles() {
  const { toast, bump } = useApp();
  const [upload, setUpload] = useState(false);
  const [edit, setEdit] = useState(null);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [deleting, setDeleting] = useState(false);
  const [search, setSearch] = useState('');
  const q = useDebounced(search);
  const res = useLoad(() => api.get('/api/files', { scope: 'mine', q, perPage: 200 }), [q]);
  const files = res.data?.items || [];
  const remove = async () => {
    if (!deleteTarget || deleting) return;
    setDeleting(true);
    try {
      await api.del('/api/files/' + deleteTarget.id);
      toast('File deleted');
      setDeleteTarget(null);
      bump();
    } catch (e) {
      toast(e.message, 'error');
    } finally {
      setDeleting(false);
    }
  };
  const verify = async (f) => {
    try {
      const r = await api.post('/api/files/' + f.id + '/verify');
      if (r.ok) toast(`Integrity verified: SHA-256 matches (${r.seconds.toFixed(2)} s)`);
      else toast(r.error || 'Integrity check failed: the stored file no longer matches its SHA-256.', 'error');
    } catch (e) { toast(e.message, 'error'); }
  };
  const toggle = async (f) => {
    try { await api.patch('/api/files/' + f.id, { visibility: f.visibility === 'public' ? 'private' : 'public' }); toast('Visibility updated'); bump(); } catch (e) { toast(e.message, 'error'); }
  };
  return (
    <>
      <Header title="My Files" subtitle="Manage the academic materials you've uploaded." actions={<Button onClick={() => setUpload(true)}><Plus size={17} /> Add file</Button>} />
      <div className="stats mini-stats">
        <Stat label="Total files" value={res.data?.total ?? '—'} Icon={FolderOpen} foot="Uploaded materials" />
        <Stat label="Public files" value={files.filter((f) => f.visibility === 'public').length} Icon={Globe} foot="Visible in library" />
        <Stat label="Private files" value={files.filter((f) => f.visibility === 'private').length} Icon={Lock} foot="Restricted access" />
      </div>
      <section className="panel">
        <div className="filters"><div className="search"><Search size={18} /><input placeholder="Search your files..." value={search} onChange={(e) => setSearch(e.target.value)} /></div></div>
        {res.loading && !files.length ? <Loading /> : files.length ? files.map((f) => (
          <div className="file-row" key={f.id}>
            <div className={'file-icon ' + f.kind.toLowerCase()}>{iconFor(f)}</div>
            <div className="file-main">
              <strong title={f.name}>{f.name}</strong>
              <span>{f.subject} · {f.category} · {fmt(f.size)} · {localDate(f.createdAt)} · {f.downloads} download{f.downloads !== 1 ? 's' : ''}</span>
            </div>
            <Tag tone={f.visibility === 'public' ? 'green' : 'purple'}>{f.visibility === 'public' ? 'Public' : 'Private'}</Tag>
            <Button variant="subtle" onClick={() => verify(f)} title="Verify SHA-256 integrity" aria-label="Verify integrity"><ShieldCheck size={16} /></Button>
            <Button variant="subtle" onClick={() => toggle(f)} title="Toggle visibility" aria-label="Toggle visibility">{f.visibility === 'public' ? <Lock size={16} /> : <Globe size={16} />}</Button>
            <Button variant="subtle" onClick={() => setEdit(f)} title="Edit title, subject and category" aria-label="Edit"><Edit3 size={16} /></Button>
            <Button variant="danger-icon" onClick={() => setDeleteTarget(f)} title="Delete" aria-label="Delete"><Trash2 size={16} /></Button>
          </div>
        )) : <Empty title="No files yet" desc="Upload your first academic material to get started." />}
      </section>
      {upload && <UploadModal onClose={() => setUpload(false)} />}
      {edit && <EditModal file={edit} onClose={() => setEdit(null)} />}
      {deleteTarget && (
        <Modal title="Delete file?" onClose={() => !deleting && setDeleteTarget(null)}>
          <div className="delete-confirm">
            <div className="delete-confirm-icon"><Trash2 size={22} aria-hidden="true" /></div>
            <p className="delete-confirm-message">Are you sure you want to delete this file?</p>
            <div className="delete-confirm-file"><FileText size={19} aria-hidden="true" /><strong>{deleteTarget.name}</strong></div>
            <p className="delete-confirm-warning">This action cannot be undone. If you shared this file with another student, it will also disappear from their inbox.</p>
            <div className="modal-actions delete-confirm-actions">
              <Button variant="secondary" onClick={() => setDeleteTarget(null)} disabled={deleting}>Cancel</Button>
              <Button variant="delete-confirm-button" onClick={remove} loading={deleting}>{deleting ? 'Deleting…' : 'Delete file'}</Button>
            </div>
          </div>
        </Modal>
      )}
    </>
  );
}

function SendPage() {
  const [recipient, setRecipient] = useState('');
  const [upload, setUpload] = useState(false);
  const users = useLoad(() => api.get('/api/users'));
  const sent = useLoad(() => api.get('/api/transfers', { box: 'sent', perPage: 20 }));
  const items = sent.data?.items || [];
  return (
    <>
      <Header title="Send Files" subtitle="Share academic materials privately with another student." />
      <div className="two-panel">
        <section className="panel send-panel">
          <div className="large-icon"><Send size={29} /></div>
          <h2>Send a file to a classmate</h2>
          <p>Choose a registered user, then attach the file you'd like to share. Only the recipient will see it in their inbox.</p>
          <label className="field-label">Send to
            <select value={recipient} onChange={(e) => setRecipient(e.target.value)}>
              <option value="">Select a student...</option>
              {(users.data?.items || []).map((u) => <option key={u.id} value={u.id}>{u.name} · @{u.username}</option>)}
            </select>
          </label>
          <Button disabled={!recipient} onClick={() => setUpload(true)}><FileUp size={18} /> Choose file and send</Button>
          <div className="note"><Shield size={17} /> Direct shares are private and routed through the FileGo server.</div>
        </section>
        <section className="panel">
          <div className="panel-title"><div><h3>Recently sent</h3><p>Files you've shared with others</p></div></div>
          {sent.loading && !items.length ? <Loading /> : items.length ? items.map((t) => (
            <div className="file-row" key={t.id}>
              <div className="file-icon pdf"><Send size={19} /></div>
              <div className="file-main"><strong>{t.name}</strong><span>To {t.recipient} · {fmt(t.size)} · {localDate(t.createdAt)}</span></div>
              <Tag tone={t.status === 'Downloaded' ? 'green' : ''}>{t.status}</Tag>
            </div>
          )) : <Empty icon={Send} title="No sent files" desc="Your shared files will appear here." />}
        </section>
      </div>
      {upload && <UploadModal mode="direct" recipientId={recipient} onClose={() => setUpload(false)} />}
    </>
  );
}

function InboxPage() {
  const [tab, setTab] = useState('received');
  const download = useDownload();
  const received = useLoad(() => api.get('/api/transfers', { box: 'received', perPage: 100 }));
  const sent = useLoad(() => api.get('/api/transfers', { box: 'sent', perPage: 100 }));
  const [preview, setPreview] = useState(null);
  const current = tab === 'received' ? received : sent;
  const items = current.data?.items || [];
  return (
    <>
      <Header title="Inbox" subtitle="Manage the files you've received and sent privately." />
      <section className="panel">
        <div className="tabs">
          <button className={tab === 'received' ? 'selected' : ''} onClick={() => setTab('received')}><ArrowDownLeft size={17} /> Received ({received.data?.total ?? 0})</button>
          <button className={tab === 'sent' ? 'selected' : ''} onClick={() => setTab('sent')}><ArrowUpRight size={17} /> Sent ({sent.data?.total ?? 0})</button>
        </div>
        {current.loading && !items.length ? <Loading /> : items.length ? items.map((t) => (
          <div className="file-row" key={t.id}>
            <div className={'file-icon ' + t.kind.toLowerCase()}><FileText /></div>
            <div className="file-main">
              <strong>{t.name}</strong>
              <span>{tab === 'received' ? 'From ' + t.sender : 'To ' + t.recipient} · {fmt(t.size)} · {localDate(t.createdAt)}</span>
            </div>
            <Tag tone={t.status === 'Downloaded' ? 'green' : 'purple'}>{tab === 'received' && t.status === 'Delivered' ? 'New' : t.status}</Tag>
            {tab === 'received' && PREVIEWABLE.includes(t.kind) && <Button variant="icon" title="Preview" onClick={() => setPreview(t)}><Eye size={18} /></Button>}
            {tab === 'received' && <Button variant="icon" title="Download" onClick={() => download(t.fileId)} aria-label={'Download ' + t.name}><Download size={18} /></Button>}
          </div>
        )) : <Empty icon={Inbox} title={tab === 'received' ? 'Your inbox is empty' : 'No files sent'} desc="Shared files will appear here." />}
      </section>
      {preview && <PreviewModal file={{ id: preview.fileId, name: preview.name, kind: preview.kind, size: preview.size }} onClose={() => setPreview(null)} />}
    </>
  );
}

const operation = (x) => (x.type === 'upload' ? 'Upload' : 'Download');
const secs = (v) => (v != null ? v.toFixed(2) + ' s' : '—');
const mbps = (v) => (v != null ? v.toFixed(2) + ' MB/s' : '—');

function HistoryPage() {
  const [page, setPage] = useState(1);
  const [type, setType] = useState('');
  const [status, setStatus] = useState('');
  const res = useLoad(() => api.get('/api/history', { page, perPage: 25, type, status }), [page, type, status]);
  const rows = res.data?.items || [];
  const filter = (setter) => (e) => { setter(e.target.value); setPage(1); };
  return (
    <>
      <Header
        title="Transfer History"
        subtitle="Review your uploads and downloads with the time, speed and resources each one used."
        actions={<a className="btn secondary" href={'/api/history/export.csv' + (type || status ? '?' + new URLSearchParams(Object.entries({ type, status }).filter(([, v]) => v)) : '')} download><Download size={16} /> Export CSV</a>}
      />
      <div className="stats mini-stats">
        <Stat label="Transfer records" value={res.data?.total ?? '—'} Icon={History} foot="Uploads and downloads" />
        <Stat label="Completed (this page)" value={rows.filter((x) => x.status === 'completed').length} Icon={CheckCircle2} foot="Successful operations" />
        <Stat label="Failed (this page)" value={rows.filter((x) => x.status === 'failed').length} Icon={AlertCircle} foot="Interrupted or rejected" />
      </div>
      <section className="panel">
        <div className="panel-title"><div><h3>Activity log</h3><p>Server time is measured by the server from the first byte to the last. Browser time is the total your device saw, including the network.</p></div></div>
        <div className="filters">
          <select value={type} onChange={filter(setType)} aria-label="Operation"><option value="">All operations</option><option value="upload">Uploads</option><option value="download">Downloads</option></select>
          <select value={status} onChange={filter(setStatus)} aria-label="Status"><option value="">All results</option><option value="completed">Completed</option><option value="failed">Failed</option></select>
        </div>
        <div className="table-wrap">
          <table>
            <thead><tr><th>File</th><th>Operation</th><th>Size</th><th>Server time</th><th>Browser time</th><th>Speed</th><th>Buffer</th><th>CPU avg</th><th>Integrity</th><th>Date</th><th>Status</th></tr></thead>
            <tbody>
              {rows.map((x) => (
                <tr key={x.id}>
                  <td><strong>{x.name}</strong></td><td>{operation(x)}</td><td>{fmt(x.size)}</td>
                  <td>{secs(x.serverSeconds)}</td>
                  <td>{secs(x.clientSeconds)}</td>
                  <td>{mbps(x.speedMBps)}</td>
                  <td>{x.bufferKb ? x.bufferKb + ' KB' : '—'}</td>
                  <td>{x.cpuAvg != null ? x.cpuAvg.toFixed(0) + '%' : '—'}</td>
                  <td>{x.sha256Verified === true ? <Tag tone="green">Verified</Tag> : x.sha256Verified === false ? <Tag>Mismatch</Tag> : '—'}</td>
                  <td>{localDate(x.createdAt)}</td>
                  <td><span title={x.error || ''}><Tag tone={x.status === 'completed' ? 'green' : ''}>{x.status === 'completed' ? 'Completed' : 'Failed'}</Tag></span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {res.loading && !rows.length ? <Loading /> : !rows.length && <Empty icon={History} title="No transfer activity" desc="Uploads and downloads will be listed here." />}
        <Pager page={page} perPage={25} total={res.data?.total || 0} onPage={setPage} />
      </section>
    </>
  );
}

const GROUP_LABELS = { size: 'File size (Test 1)', buffer: 'Buffer size (Test 2)', concurrency: 'Simultaneous transfers (Test 3)', label: 'Experiment label (Tests 4 and 5)', device: 'Client device (Test 5)' };

function ExperimentControls() {
  const { toast } = useApp();
  const [label, setLabel] = useState('');
  const [note, setNote] = useState('');
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    api.get('/api/metrics/experiment').then((e) => { setLabel(e.label || ''); setNote(e.networkNote || ''); }).catch(() => {});
  }, []);
  const save = async () => {
    setSaving(true);
    try {
      await request('/api/metrics/experiment', { method: 'PUT', json: { label, networkNote: note } });
      toast(label ? 'Experiment label set' : 'Experiment label cleared');
    } catch (e) { toast(e.message, 'error'); }
    setSaving(false);
  };
  return (
    <section className="panel">
      <div className="panel-title"><div><h3>Experiment labels</h3><p>Applied to every transfer made while set, so repeated tests can be grouped and the network conditions are recorded</p></div></div>
      <div className="two-col">
        <label className="field-label">Label<input value={label} maxLength={80} onChange={(e) => setLabel(e.target.value)} placeholder="Test 2, 256 KB" /></label>
        <label className="field-label">Network note<input value={note} maxLength={255} onChange={(e) => setNote(e.target.value)} placeholder="Phone hotspot, laptop on AC, 2 m apart" /></label>
      </div>
      <div className="modal-actions"><Button loading={saving} onClick={save}>Save label</Button></div>
    </section>
  );
}

function Performance() {
  const { user } = useApp();
  const isAdmin = user.role === 'admin';
  const [live, setLive] = useState(null);
  const [groupBy, setGroupBy] = useState('size');
  const [type, setType] = useState('upload');
  const [scope, setScope] = useState('mine');
  useEffect(() => {
    let alive = true;
    const poll = () => api.get('/api/metrics/live').then((r) => alive && setLive(r)).catch(() => {});
    poll();
    const t = setInterval(poll, 2000);
    return () => { alive = false; clearInterval(t); };
  }, []);
  const sum = useLoad(() => api.get('/api/metrics/summary', { groupBy, type, scope }), [groupBy, type, scope]);
  const cur = live?.current;
  const series = (live?.samples || []).slice(-120).map((s, i) => ({ name: new Date(s.t).toLocaleTimeString(), cpu: s.cpu, ram: s.ramPercent, active: s.active, i }));
  const items = sum.data?.items || [];
  const overall = sum.data?.overall;
  const bars = items.map((g) => ({ name: g.group, speed: g.avgSpeedMBps ?? 0, cpu: g.avgCpu ?? 0, seconds: g.avgSeconds ?? 0 }));
  const net = live?.system;
  return (
    <>
      <Header title="Performance Monitor" subtitle="Live server resources and measured transfer performance." />
      <div className="stats">
        <Stat label="Server CPU" value={cur ? cur.cpu.toFixed(0) + '%' : '—'} Icon={Cpu} foot={cur ? `${live.current.cpuCount || ''} logical cores, live` : 'Whole machine, live'} />
        <Stat label="Server RAM" value={cur ? cur.ramPercent.toFixed(0) + '%' : '—'} Icon={MemoryStick} foot={cur ? `FileGo process: ${cur.procMb.toFixed(0)} MB` : 'Live'} />
        <Stat label="Transfers in progress" value={cur ? cur.active : '—'} Icon={Activity} foot={live ? `${live.serverMode} mode, ${live.bufferKb} KB buffer` : 'Live'} />
        <Stat label="Success rate" value={overall?.successRate != null ? overall.successRate + '%' : '—'} Icon={CheckCircle2} foot={overall ? `${overall.completed} of ${overall.count} transfers` : 'Selected transfers'} />
      </div>

      <section className="panel">
        <div className="panel-title"><div><h3>Live server load</h3><p>CPU and memory of the server over the last few minutes (percent)</p></div></div>
        <div className="chart">{series.length > 1 ? (
          <ResponsiveContainer width="100%" height="100%"><AreaChart data={series}><CartesianGrid strokeDasharray="3 3" vertical={false} /><XAxis dataKey="name" minTickGap={40} /><YAxis domain={[0, 100]} /><Tooltip /><Area type="monotone" dataKey="cpu" name="CPU %" stroke="#6879e8" fill="#6c7ef6" fillOpacity={0.2} strokeWidth={2} isAnimationActive={false} /><Area type="monotone" dataKey="ram" name="RAM %" stroke="#46b78c" fill="#46b78c" fillOpacity={0.12} strokeWidth={2} isAnimationActive={false} /></AreaChart></ResponsiveContainer>
        ) : <Empty icon={Cpu} title="Collecting samples" desc="The graph fills in a few seconds after the server starts sampling." />}</div>
        {net && <div className="note"><Wifi size={16} /><span>Server disk used: {fmt(net.diskUsedBytes)} of {fmt(net.diskTotalBytes)}. Network since boot: {fmt(net.netBytesSent)} sent, {fmt(net.netBytesRecv)} received.</span></div>}
      </section>

      <section className="panel">
        <div className="panel-title"><div><h3>Transfer comparison</h3><p>Average speed and CPU for the group you choose. Speed is size divided by server time.</p></div></div>
        <div className="filters">
          <select value={groupBy} onChange={(e) => setGroupBy(e.target.value)} aria-label="Group by">{Object.entries(GROUP_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
          <select value={type} onChange={(e) => setType(e.target.value)} aria-label="Operation"><option value="upload">Uploads</option><option value="download">Downloads</option></select>
          {isAdmin && <select value={scope} onChange={(e) => setScope(e.target.value)} aria-label="Whose transfers"><option value="mine">My transfers</option><option value="all">All users</option></select>}
        </div>
        {sum.data?.note && <div className="notice"><AlertCircle size={18} /><div><strong>Timing note</strong><p>{sum.data.note}</p></div></div>}
        <div className="two-panel">
          <div>
            <h3>Average speed (MB/s)</h3>
            <div className="chart">{bars.length ? (
              <ResponsiveContainer width="100%" height="100%"><BarChart data={bars}><CartesianGrid strokeDasharray="3 3" vertical={false} /><XAxis dataKey="name" /><YAxis /><Tooltip /><Bar dataKey="speed" name="MB/s" fill="#8d9bf2" radius={[5, 5, 0, 0]} /></BarChart></ResponsiveContainer>
            ) : <Empty icon={ChartNoAxesCombined} title="No measurements yet" desc="Make some transfers to see them compared here." />}</div>
          </div>
          <div>
            <h3>Average CPU during transfer (%)</h3>
            <div className="chart">{bars.length ? (
              <ResponsiveContainer width="100%" height="100%"><BarChart data={bars}><CartesianGrid strokeDasharray="3 3" vertical={false} /><XAxis dataKey="name" /><YAxis domain={[0, 100]} /><Tooltip /><Bar dataKey="cpu" name="CPU %" fill="#6bc3a3" radius={[5, 5, 0, 0]} /></BarChart></ResponsiveContainer>
            ) : <Empty icon={Cpu} title="No measurements yet" desc="CPU readings are recorded for every transfer." />}</div>
          </div>
        </div>
        {items.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Group</th><th>Transfers</th><th>Success</th><th>Avg speed</th><th>Median speed</th><th>Avg server time</th><th>Avg browser time</th><th>Disk write</th><th>Hashing</th><th>Avg CPU</th><th>Peak CPU</th><th>Server RAM</th></tr></thead>
              <tbody>{items.map((g) => (
                <tr key={g.group}>
                  <td><strong>{g.group}</strong></td><td>{g.count}</td><td>{g.successRate != null ? g.successRate + '%' : '—'}</td>
                  <td>{mbps(g.avgSpeedMBps)}</td><td>{mbps(g.medianSpeedMBps)}</td><td>{secs(g.avgSeconds)}</td><td>{secs(g.avgClientSeconds)}</td>
                  <td>{secs(g.avgWriteSeconds)}</td><td>{secs(g.avgHashSeconds)}</td>
                  <td>{g.avgCpu != null ? g.avgCpu.toFixed(0) + '%' : '—'}</td><td>{g.peakCpu != null ? g.peakCpu.toFixed(0) + '%' : '—'}</td><td>{g.avgRamProcMb != null ? g.avgRamProcMb.toFixed(0) + ' MB' : '—'}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
        <div className="note"><AlertCircle size={16} /><span>Server time starts at the first byte and ends at the last, so it matches the network only in the streaming server mode. Browser time includes everything your device saw. Readings come from the same laptop that is serving the files.</span></div>
      </section>
      {isAdmin && <ExperimentControls />}
    </>
  );
}

function SettingsPage() {
  const { user, setUser, theme, setTheme, toast, meta } = useApp();
  const [name, setName] = useState(user.name);
  const [email, setEmail] = useState(user.email || '');
  const [emailPw, setEmailPw] = useState('');
  const [cur, setCur] = useState('');
  const [next, setNext] = useState('');
  const net = useLoad(() => api.get('/api/network'));

  const saveProfile = async (e) => {
    e.preventDefault();
    const body = { name };
    if ((email || '') !== (user.email || '')) { body.email = email; body.currentPassword = emailPw; }
    try {
      const r = await api.patch('/api/users/me', body);
      setUser(r.user);
      setEmailPw('');
      toast('Profile updated');
    } catch (err) { toast(err.message, 'error'); }
  };
  const savePassword = async (e) => {
    e.preventDefault();
    try {
      await api.post('/api/users/me/password', { currentPassword: cur, newPassword: next });
      setCur(''); setNext('');
      setUser({ ...user, mustChangePassword: false });
      toast('Password changed. Other devices were signed out.');
    } catch (err) { toast(err.message, 'error'); }
  };
  const emailChanged = (email || '') !== (user.email || '') && email !== '';

  return (
    <>
      <Header title="Settings" subtitle="Manage your profile and application preferences." />
      <div className="settings-grid">
        <section className="panel">
          <div className="panel-title"><div><h3>Personal information</h3><p>Signed in as @{user.username}</p></div></div>
          <div className="settings-avatar">{initials(user.name)}</div>
          <form className="form-stack" onSubmit={saveProfile}>
            <label>Full name<input required value={name} onChange={(e) => setName(e.target.value)} maxLength={80} /></label>
            <label>Email address (optional)<input type="email" value={email} onChange={(e) => setEmail(e.target.value)} /></label>
            {emailChanged && <label>Current password (needed to change email)<input type="password" required value={emailPw} onChange={(e) => setEmailPw(e.target.value)} autoComplete="current-password" /></label>}
            <Button type="submit">Save changes</Button>
          </form>
        </section>
        <section className="panel">
          <div className="panel-title"><div><h3>Change password</h3><p>At least 8 characters</p></div></div>
          <form className="form-stack" onSubmit={savePassword}>
            <label>Current password<input type="password" required value={cur} onChange={(e) => setCur(e.target.value)} autoComplete="current-password" /></label>
            <label>New password<input type="password" required minLength={8} value={next} onChange={(e) => setNext(e.target.value)} autoComplete="new-password" /></label>
            <Button type="submit">Update password</Button>
          </form>
        </section>
        <section className="panel">
          <div className="panel-title"><div><h3>Appearance & server</h3><p>Personalize FileGo and see how to reach this server</p></div></div>
          <label className="field-label">Color theme
            <select value={theme} onChange={(e) => setTheme(e.target.value)}><option value="light">Light</option><option value="dark">Dark</option></select>
          </label>
          <div className="setting-info"><strong>Current role</strong><span>{user.role}</span></div>
          <div className="setting-info"><strong>Server mode</strong><span>{meta?.serverMode || '—'}</span></div>
          <div className="setting-info"><strong>Upload limit</strong><span>{meta?.maxUploadMb} MB per file</span></div>
          <div className="setting-info"><strong>Network address</strong><span>{net.data?.urls?.length ? net.data.urls.join(' · ') : 'Not detected'}</span></div>
          <div className="note"><AlertCircle size={17} /> FileGo uses plain HTTP on your local network. Do not reuse a password from another service.</div>
        </section>
      </div>
    </>
  );
}

function TempPasswordModal({ result, onClose }) {
  const { toast } = useApp();
  const copy = async () => {
    try { await navigator.clipboard.writeText(result.temporaryPassword); toast('Copied'); } catch { toast('Copy it by hand', 'error'); }
  };
  return (
    <Modal title="Temporary password" subtitle={`For ${result.user.name} (@${result.user.username})`} onClose={onClose}>
      <p>Give this password to the student. It is shown only once, and they must choose a new one when they log in.</p>
      <div className="demo-hint"><strong style={{ fontFamily: 'monospace', fontSize: 22, letterSpacing: 1 }}>{result.temporaryPassword}</strong></div>
      <div className="modal-actions"><Button variant="secondary" onClick={copy}>Copy</Button><Button onClick={onClose}>Done</Button></div>
    </Modal>
  );
}

function Admin() {
  const { user, toast, bump } = useApp();
  const [fileSearch, setFileSearch] = useState('');
  const [visibility, setVisibility] = useState('');
  const [filePage, setFilePage] = useState(1);
  const [temp, setTemp] = useState(null);
  const fq = useDebounced(fileSearch);
  const stats = useLoad(() => api.get('/api/admin/stats'));
  const users = useLoad(() => api.get('/api/admin/users', { perPage: 200 }));
  const files = useLoad(() => api.get('/api/admin/files', { q: fq, visibility, page: filePage, perPage: 25 }), [fq, visibility, filePage]);
  if (user.role !== 'admin') return <Navigate to="/dashboard" />;
  const list = files.data?.items || [];
  const people = users.data?.items || [];
  const s = stats.data;
  const act = async (fn, ok) => {
    try { const r = await fn(); if (ok) toast(ok); bump(); return r; } catch (e) { toast(e.message, 'error'); return null; }
  };
  const remove = (f) => {
    if (!window.confirm(`Remove "${f.name}" from the system?\n\nIt will also disappear from any inbox it was sent to. This cannot be undone.`)) return;
    act(() => api.del('/api/admin/files/' + f.id), 'File removed');
  };
  const setActive = (u, isActive) => {
    if (!isActive && !window.confirm(`Deactivate ${u.name}? They will be logged out and cannot sign in.`)) return;
    act(() => api.patch('/api/admin/users/' + u.id, { isActive }), isActive ? 'Account activated' : 'Account deactivated');
  };
  const setRole = (u, role) => {
    if (!window.confirm(role === 'admin' ? `Make ${u.name} an administrator? Administrators can see every file.` : `Remove administrator rights from ${u.name}?`)) return;
    act(() => api.patch('/api/admin/users/' + u.id, { role }), 'Role updated');
  };
  const reset = async (u) => {
    if (!window.confirm(`Reset the password for ${u.name}? They will be logged out.`)) return;
    const r = await act(() => api.post('/api/admin/users/' + u.id + '/reset-password'));
    if (r) setTemp(r);
  };
  return (
    <>
      <Header
        title="Administration"
        subtitle="Manage users and shared files, and view system-wide statistics."
        actions={<a className="btn secondary" href="/api/admin/transfers/export.csv" download><Download size={16} /> Export all transfers (CSV)</a>}
      />
      <div className="stats">
        <Stat label="Registered users" value={s ? s.users.total : '—'} Icon={Users} foot={s ? `${s.users.active} active, ${s.users.admins} administrator${s.users.admins !== 1 ? 's' : ''}` : 'Accounts'} />
        <Stat label="Files" value={s ? s.files.total : '—'} Icon={FolderOpen} foot={s ? `${s.files.public} public, ${s.files.private} private` : 'All materials'} />
        <Stat label="Storage used by files" value={s ? fmt(s.files.storageBytes) : '—'} Icon={HardDrive} foot={s ? `Disk free: ${fmt(s.disk.freeBytes)}` : 'On the server'} />
        <Stat label="Transfer success" value={s?.activity.successRate != null ? s.activity.successRate + '%' : '—'} Icon={CheckCircle2} foot={s ? `${s.activity.uploads} uploads, ${s.activity.downloads} downloads, ${s.activity.failed} failed` : 'All users'} />
      </div>
      {s && (
        <div className="two-panel">
          <section className="panel">
            <div className="panel-title"><div><h3>Files by subject</h3><p>Where the library's content is</p></div></div>
            {s.bySubject.length ? s.bySubject.map((x) => <div className="setting-info" key={x.subject}><strong>{x.subject}</strong><span>{x.files} file{x.files !== 1 ? 's' : ''}</span></div>) : <Empty title="No files yet" />}
          </section>
          <section className="panel">
            <div className="panel-title"><div><h3>Top uploaders</h3><p>By storage used</p></div></div>
            {s.topUploaders.length ? s.topUploaders.map((x) => <div className="setting-info" key={x.id}><strong>{x.name}</strong><span>{x.files} file{x.files !== 1 ? 's' : ''} · {fmt(x.storageBytes)}</span></div>) : <Empty title="No uploads yet" />}
            <div className="setting-info"><strong>Direct sends</strong><span>{s.transfers.sent} total · {s.transfers.delivered} waiting · {s.transfers.downloaded} downloaded</span></div>
          </section>
        </div>
      )}
      <section className="panel">
        <div className="panel-title"><div><h3>Users</h3><p>Deactivating an account logs the person out immediately</p></div></div>
        {users.loading && !people.length ? <Loading /> : people.map((u) => (
          <div className="file-row" key={u.id}>
            <div className="avatar">{initials(u.name)}</div>
            <div className="file-main"><strong>{u.name}</strong><span>@{u.username} · {u.fileCount} file{u.fileCount !== 1 ? 's' : ''} · {fmt(u.storageBytes)}{u.lastLoginAt ? ' · last login ' + localDate(u.lastLoginAt) : ''}</span></div>
            <Tag tone={u.role === 'admin' ? 'purple' : ''}>{u.role === 'admin' ? 'Administrator' : 'Student'}</Tag>
            <Tag tone={u.isActive ? 'green' : ''}>{u.isActive ? 'Active' : 'Deactivated'}</Tag>
            {u.id !== user.id && (
              <>
                <Button variant="secondary" onClick={() => reset(u)}>Reset password</Button>
                <Button variant="secondary" onClick={() => setRole(u, u.role === 'admin' ? 'student' : 'admin')}>{u.role === 'admin' ? 'Make student' : 'Make admin'}</Button>
                <Button variant="secondary" onClick={() => setActive(u, !u.isActive)}>{u.isActive ? 'Deactivate' : 'Activate'}</Button>
              </>
            )}
          </div>
        ))}
      </section>
      <section className="panel">
        <div className="panel-title"><div><h3>All files</h3><p>Public and private. Administrators can see and remove any file.</p></div></div>
        <div className="filters">
          <div className="search"><Search size={18} /><input placeholder="Search by title or uploader..." value={fileSearch} onChange={(e) => { setFileSearch(e.target.value); setFilePage(1); }} /></div>
          <select value={visibility} onChange={(e) => { setVisibility(e.target.value); setFilePage(1); }} aria-label="Visibility"><option value="">All files</option><option value="public">Public</option><option value="private">Private</option></select>
        </div>
        {files.loading && !list.length ? <Loading /> : list.length ? list.map((f) => (
          <div className="file-row" key={f.id}>
            <div className={'file-icon ' + (f.kind || '').toLowerCase()}>{iconFor(f)}</div>
            <div className="file-main"><strong title={f.name}>{f.name}</strong><span>{f.subject} · {fmt(f.size)} · {f.owner} · {f.downloads} download{f.downloads !== 1 ? 's' : ''}</span></div>
            <Tag tone={f.visibility === 'public' ? 'green' : 'purple'}>{f.visibility === 'public' ? 'Public' : 'Private'}</Tag>
            <Button variant="danger-icon" onClick={() => remove(f)} aria-label={'Remove ' + f.name} title="Remove from the system"><Trash2 size={17} /></Button>
          </div>
        )) : <Empty title="No files found" desc="Nothing matches this search." />}
        <Pager page={filePage} perPage={25} total={files.data?.total || 0} onPage={setFilePage} />
      </section>
      {temp && <TempPasswordModal result={temp} onClose={() => setTemp(null)} />}
    </>
  );
}

/* ------------------------------------------------------------------ login and register */

function Auth() {
  const { user, setUser, toast } = useApp();
  const navigate = useNavigate();
  const loc = useLocation();
  const registering = loc.pathname === '/register';
  const [name, setName] = useState('');
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  if (user) return <Navigate to="/dashboard" replace />;

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      const u = registering
        ? await apiRegister({ name, username, email: email || undefined, password })
        : await apiLogin(username, password);
      setUser(u);
      navigate('/dashboard');
    } catch (err) { toast(err.message, 'error'); setBusy(false); }
  };

  return (
    <div className="auth-page">
      <div className="auth-side">
        <div className="auth-logo"><div className="brand-mark"><img src="/filego-logo.png" alt="" /></div><strong>FileGo</strong></div>
        <div className="auth-message">
          <h1>Keep coursework organized. <em>Share it simply.</em></h1>
          <p>A simpler way to share academic materials, exchange reviewers, and collaborate over your local network.</p>
          <div className="auth-illustration">
            <div className="auth-floating"><FileText size={23} /> Reviewer.pdf <CheckCircle2 size={19} /></div>
            <div className="auth-floating"><BookOpen size={23} /> Lecture Notes <CheckCircle2 size={19} /></div>
            <div className="auth-floating"><Send size={23} /> Shared with a classmate <CheckCircle2 size={19} /></div>
          </div>
        </div>
        <small>Share files. Exchange knowledge. Stay connected.</small>
      </div>
      <div className="auth-form-wrap">
        <div className="auth-form">
          <div className="mobile-brand"><FolderOpen /> FileGo</div>
          <h2>{registering ? 'Create your account' : 'Welcome back'}</h2>
          <p>{registering ? 'Join your academic sharing community.' : 'Sign in to continue to your academic workspace.'}</p>
          <form onSubmit={submit} className="form-stack">
            {registering && <label>Full name<input required value={name} onChange={(e) => setName(e.target.value)} placeholder="Your full name" maxLength={80} autoComplete="name" /></label>}
            <label>Username
              <input required value={username} onChange={(e) => setUsername(e.target.value)} placeholder="e.g. juan.delacruz" autoComplete="username" autoCapitalize="none" spellCheck={false} />
            </label>
            {registering && <label>Email address (optional)<input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="student@example.com" autoComplete="email" /></label>}
            <label>Password
              <input required type="password" minLength={registering ? 8 : undefined} value={password} onChange={(e) => setPassword(e.target.value)} placeholder={registering ? 'At least 8 characters' : 'Enter password'} autoComplete={registering ? 'new-password' : 'current-password'} />
            </label>
            <Button type="submit" loading={busy}>{registering ? 'Create account' : 'Sign in'} <ChevronRight size={18} /></Button>
          </form>
          <div className="auth-switch">{registering ? 'Already have an account?' : 'New to FileGo?'} <Link to={registering ? '/login' : '/register'}>{registering ? 'Sign in' : 'Create an account'}</Link></div>
          {DEMO_MODE && (
            <div className="demo-hint"><strong>Demo access</strong><span>student / demo123 (administrator)</span><small>Also: alex and jamie, same password.</small></div>
          )}
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ router */

const routes = { '/dashboard': Dashboard, '/library': Library, '/my-files': MyFiles, '/send': SendPage, '/inbox': InboxPage, '/history': HistoryPage, '/performance': Performance, '/settings': SettingsPage, '/admin': Admin };

function Router() {
  const loc = useLocation();
  const { booting, user } = useApp();
  if (booting) return <div className="boot"><RefreshCw size={28} className="spin" /></div>;
  if (['/login', '/register'].includes(loc.pathname)) return <Auth />;
  const Page = routes[loc.pathname];
  if (!Page) return <Navigate to={user ? '/dashboard' : '/login'} replace />;
  return <Shell><Page /></Shell>;
}

function App() {
  return <BrowserRouter><Provider><Router /></Provider></BrowserRouter>;
}

createRoot(document.getElementById('root')).render(<App />);
