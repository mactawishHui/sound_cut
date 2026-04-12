import { useState, useRef, useCallback, useEffect, DragEvent } from 'react'
import './App.css'

// ─── Types ──────────────────────────────────────────────────────────────────

interface Config {
  cut: boolean
  auto_volume: boolean
  enhance_speech: boolean
  subtitle: boolean
  aggressiveness: string
  min_silence_ms: string
  padding_ms: string
  crossfade_ms: string
  target_lufs: string
  enhancer_backend: string
  enhancer_profile: string
  enhancer_fallback: string
  model_path: string
  subtitle_format: string
  subtitle_language: string
  subtitle_embed_mode: string   // 'mp4' | 'mkv' | 'burn' | 'sidecar'
  subtitle_max_chars: string
  keep_temp: boolean
}

interface JobResult {
  input_duration_s: number
  output_duration_s: number
  removed_duration_s: number
  kept_segment_count: number
  has_subtitle: boolean
  output_filename: string
  subtitle_filename: string | null
}

type AppState = 'idle' | 'processing' | 'done' | 'error'

const DEFAULT_CONFIG: Config = {
  cut: false, auto_volume: false, enhance_speech: true, subtitle: false,
  aggressiveness: 'balanced',
  min_silence_ms: '', padding_ms: '', crossfade_ms: '', target_lufs: '',
  enhancer_backend: 'deepfilternet3', enhancer_profile: 'natural', enhancer_fallback: 'fail',
  model_path: '',
  subtitle_format: 'srt', subtitle_language: '', subtitle_embed_mode: 'mp4',
  subtitle_max_chars: '25',
  keep_temp: false,
}

// ─── Helpers ────────────────────────────────────────────────────────────────

const AUDIO_EXTS = new Set(['mp3', 'm4a', 'wav', 'aac', 'ogg', 'flac', 'wma', 'opus'])

const isAudio = (f: File | null) => {
  if (!f) return false
  const ext = f.name.split('.').pop()?.toLowerCase() ?? ''
  return AUDIO_EXTS.has(ext)
}

const LANGUAGES = [
  { v: '',    l: '自动识别' },
  { v: 'zh',  l: '中文（普通话）' },
  { v: 'yue', l: '粤语' },
  { v: 'en',  l: 'English' },
  { v: 'ja',  l: '日本語' },
  { v: 'ko',  l: '한국어' },
  { v: 'es',  l: 'Español' },
  { v: 'fr',  l: 'Français' },
  { v: 'de',  l: 'Deutsch' },
  { v: 'ru',  l: 'Русский' },
]

const EMBED_MODES_VIDEO = [
  { v: 'mp4',    l: 'MP4 内嵌',     d: 'mov_text 软字幕，兼容性好' },
  { v: 'mkv',    l: 'MKV 软字幕',   d: '可在播放器中独立切换' },
  { v: 'burn',   l: '硬烧录字幕',   d: '字幕烧入画面，任何播放器' },
  { v: 'sidecar',l: '仅字幕文件',   d: '不修改视频，只输出 .srt' },
]

const EMBED_MODES_AUDIO = [
  { v: 'sidecar', l: '输出字幕文件', d: '音频文件仅支持输出独立字幕文件' },
]

// ─── API helpers ────────────────────────────────────────────────────────────

async function submitJob(file: File, cfg: Config): Promise<string> {
  // Convert subtitle_embed_mode to the three boolean flags the API expects
  const apiCfg = {
    ...cfg,
    subtitle_sidecar: cfg.subtitle_embed_mode === 'sidecar',
    subtitle_mkv:     cfg.subtitle_embed_mode === 'mkv',
    subtitle_burn:    cfg.subtitle_embed_mode === 'burn',
  }
  const form = new FormData()
  form.append('file', file)
  form.append('config', JSON.stringify(apiCfg))
  const res = await fetch('/api/jobs', { method: 'POST', body: form })
  if (!res.ok) { const e = await res.json(); throw new Error(e.error || 'Upload failed') }
  return (await res.json()).job_id
}

async function pollJob(id: string) {
  return (await fetch(`/api/jobs/${id}`)).json()
}

const dlUrl = (id: string, a: 'output' | 'subtitle') => `/api/jobs/${id}/download/${a}`

// ─── Spectrum animation ──────────────────────────────────────────────────────

function Spectrum() {
  return (
    <div className="spectrum">
      {Array.from({ length: 14 }, (_, i) => (
        <div key={i} className="bar" style={{ animationDelay: `${i * 0.06}s` }} />
      ))}
    </div>
  )
}

// ─── Toggle switch ───────────────────────────────────────────────────────────

function Toggle({ on, onChange }: { on: boolean; onChange: (v: boolean) => void }) {
  return (
    <div className={`toggle ${on ? 'toggle--on' : ''}`}
      onClick={e => { e.stopPropagation(); onChange(!on) }}>
      <div className="toggle-thumb" />
    </div>
  )
}

// ─── Labeled field ───────────────────────────────────────────────────────────

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="field">
      <span className="field-lbl mono">{label}</span>
      {children}
    </div>
  )
}

// ─── Subtitle embed mode radio group ─────────────────────────────────────────

function EmbedModeGroup({
  value, onChange, audioFile,
}: { value: string; onChange: (v: string) => void; audioFile: boolean }) {
  const modes = audioFile ? EMBED_MODES_AUDIO : EMBED_MODES_VIDEO
  return (
    <div className="embed-group">
      {modes.map(({ v, l, d }) => (
        <button
          key={v}
          type="button"
          className={`embed-btn ${value === v ? 'embed-btn--on' : ''}`}
          onClick={() => onChange(v)}
        >
          <span className="embed-lbl">{l}</span>
          <span className="embed-desc">{d}</span>
        </button>
      ))}
    </div>
  )
}

// ─── App ────────────────────────────────────────────────────────────────────

export default function App() {
  const [file, setFile]         = useState<File | null>(null)
  const [drag, setDrag]         = useState(false)
  const [cfg, setCfg]           = useState<Config>(DEFAULT_CONFIG)
  const [showAdv, setShowAdv]   = useState(false)
  const [appState, setAppState] = useState<AppState>('idle')
  const [jobId, setJobId]       = useState<string | null>(null)
  const [result, setResult]     = useState<JobResult | null>(null)
  const [errMsg, setErrMsg]     = useState('')
  const [elapsed, setElapsed]   = useState(0)
  const fileRef  = useRef<HTMLInputElement>(null)
  const startRef = useRef(0)
  const pollRef  = useRef<ReturnType<typeof setInterval> | null>(null)

  // Elapsed timer while processing
  useEffect(() => {
    if (appState !== 'processing') return
    startRef.current = Date.now()
    const t = setInterval(() => setElapsed(Math.floor((Date.now() - startRef.current) / 1000)), 400)
    return () => clearInterval(t)
  }, [appState])

  // Force sidecar when audio file is uploaded
  useEffect(() => {
    if (isAudio(file) && cfg.subtitle_embed_mode !== 'sidecar')
      setCfg(p => ({ ...p, subtitle_embed_mode: 'sidecar' }))
  }, [file])

  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current) }, [])

  const set = useCallback(<K extends keyof Config>(k: K, v: Config[K]) =>
    setCfg(p => ({ ...p, [k]: v })), [])

  const handleFile = (f: File) => setFile(f)

  const onDrop = (e: DragEvent) => {
    e.preventDefault(); setDrag(false)
    const f = e.dataTransfer.files[0]; if (f) handleFile(f)
  }

  const handleSubmit = async () => {
    if (!file) return
    if (!cfg.cut && !cfg.auto_volume && !cfg.enhance_speech && !cfg.subtitle) {
      setErrMsg('请至少启用一种处理功能'); return
    }
    setErrMsg(''); setAppState('processing'); setResult(null); setElapsed(0)
    try {
      const id = await submitJob(file, cfg)
      setJobId(id)
      pollRef.current = setInterval(async () => {
        try {
          const j = await pollJob(id)
          if (j.status === 'done') {
            clearInterval(pollRef.current!); setResult(j.result); setAppState('done')
          } else if (j.status === 'error') {
            clearInterval(pollRef.current!); setErrMsg(j.error || '处理失败'); setAppState('error')
          }
        } catch {}
      }, 2000)
    } catch (e: unknown) { setErrMsg((e as Error).message); setAppState('error') }
  }

  const reset = () => {
    setAppState('idle'); setFile(null); setResult(null); setJobId(null); setErrMsg('')
  }

  const anyMode    = cfg.cut || cfg.auto_volume || cfg.enhance_speech || cfg.subtitle
  const showStep03 = cfg.cut || cfg.subtitle
  const audioFile  = isAudio(file)
  const fmtTime    = (s: number) =>
    `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`

  return (
    <div className="app">

      {/* ── Topbar ── */}
      <header className="topbar" style={{ animation: 'fadeIn 0.4s ease' }}>
        <div className="brand">
          <div className="brand-ico">
            <svg width="19" height="19" viewBox="0 0 24 24" fill="none">
              <path d="M2 12h2.5l2-7 3 14 2.5-9 2 4 2-2H22"
                stroke="white" strokeWidth="2.1" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
          </div>
          <span className="brand-name serif-sc">声剪</span>
          <span className="brand-en mono">SoundCut</span>
        </div>
        <div className="status-row">
          <span className="status-dot" />
          <span className="mono" style={{ fontSize: '0.7rem', color: 'var(--muted)', letterSpacing: '0.06em' }}>LOCAL</span>
        </div>
      </header>

      {/* ── Hero ── */}
      <section className="hero" style={{ animation: 'fadeUp 0.5s 0.04s ease both' }}>
        <div className="hero-blob" />
        <div className="hero-kicker mono">◎ 音频 / 视频处理工作台</div>
        <h1 className="hero-h1 serif-sc">让<em>声音</em>只留<em>精华</em></h1>
        <p className="hero-desc">
          上传音频或视频，选择需要的处理项。<br />
          静音裁切、音量均衡、语音增强、字幕生成——可单独使用，也可全部叠加。
        </p>
      </section>

      <main className="main">

        {/* ── Error ── */}
        {errMsg && (
          <div className="alert" style={{ animation: 'fadeUp 0.25s ease' }}>⚠ {errMsg}</div>
        )}

        {/* ── Result card ── */}
        {appState === 'done' && result && jobId && (
          <div className="result" style={{ animation: 'fadeUp 0.4s ease' }}>
            <div className="result-hd">
              <div className="result-check">✓</div>
              <div>
                <div className="result-title">处理完成</div>
                <div className="result-meta mono">耗时 {elapsed}s · 结果已就绪</div>
              </div>
              <button className="btn-ghost" onClick={reset}>重新处理</button>
            </div>
            <div className="metrics">
              {([
                [result.input_duration_s.toFixed(2) + 's', 'ORIGINAL'],
                [result.output_duration_s.toFixed(2) + 's', 'OUTPUT'],
                [result.removed_duration_s.toFixed(2) + 's', 'REMOVED'],
                [String(result.kept_segment_count), 'SEGMENTS'],
              ] as [string, string][]).map(([v, l]) => (
                <div className="metric" key={l}>
                  <strong className="mono">{v}</strong>
                  <span className="mono">{l}</span>
                </div>
              ))}
            </div>
            <div className="dl-row">
              <a className="btn-dl" href={dlUrl(jobId, 'output')} download>
                <svg width="13" height="13" viewBox="0 0 16 16" fill="none">
                  <path d="M8 2v8M4 7l4 4 4-4M2 13h12" stroke="currentColor"
                    strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
                下载处理结果
              </a>
              {result.has_subtitle && (
                <a className="btn-dl btn-dl--sec" href={dlUrl(jobId, 'subtitle')} download>
                  <svg width="13" height="13" viewBox="0 0 16 16" fill="none">
                    <path d="M8 2v8M4 7l4 4 4-4M2 13h12" stroke="currentColor"
                      strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"/>
                  </svg>
                  下载字幕文件
                </a>
              )}
            </div>
          </div>
        )}

        {/* ── Processing ── */}
        {appState === 'processing' && (
          <div className="proc-card" style={{ animation: 'fadeUp 0.3s ease' }}>
            <Spectrum />
            <div className="proc-body">
              <div className="proc-label mono">PROCESSING</div>
              <div className="proc-file">{file?.name}</div>
              <div className="proc-timer mono">{fmtTime(elapsed)}</div>
              <p className="proc-hint">正在处理中，请稍候。大文件或语音增强可能需要数分钟。</p>
            </div>
          </div>
        )}

        {/* ── Form (hidden when processing) ── */}
        <div style={{ display: appState === 'processing' ? 'none' : 'contents' }}>

          {/* STEP 01: Upload */}
          <section className="card" style={{ animation: 'fadeUp 0.45s 0.10s ease both' }}>
            <div className="card-hd">
              <div className="card-ico">📁</div>
              <div>
                <div className="card-step mono">STEP 01</div>
                <div className="card-title">上传源文件</div>
              </div>
            </div>
            <div className="card-bd">
              <div
                className={`dropzone ${drag ? 'dropzone--drag' : ''} ${file ? 'dropzone--file' : ''}`}
                onDragOver={e => { e.preventDefault(); setDrag(true) }}
                onDragLeave={() => setDrag(false)}
                onDrop={onDrop}
                onClick={() => fileRef.current?.click()}
              >
                <input ref={fileRef} type="file" hidden
                  accept=".mp3,.m4a,.wav,.mp4,.mov,.mkv,.flv,.webm,.aac,.ogg"
                  onChange={e => e.target.files?.[0] && handleFile(e.target.files[0])} />
                {file ? (
                  <>
                    <div className="dz-ico">{audioFile ? '🎵' : '🎬'}</div>
                    <div className="dz-name mono">{file.name}</div>
                    <div className="dz-hint">
                      {(file.size / 1e6).toFixed(1)} MB
                      {' · '}
                      <span style={{ color: audioFile ? 'var(--amber)' : 'var(--green)' }}>
                        {audioFile ? '音频文件' : '视频文件'}
                      </span>
                      {' · 点击重新选择'}
                    </div>
                  </>
                ) : (
                  <>
                    <div className="dz-ico">↑</div>
                    <div className="dz-title">点击选择文件，或拖放到这里</div>
                    <div className="dz-hint mono">MP3 · M4A · WAV · MP4 · MKV · MOV · WEBM</div>
                  </>
                )}
              </div>
            </div>
          </section>

          {/* STEP 02: Modes */}
          <section className="card" style={{ animation: 'fadeUp 0.45s 0.16s ease both' }}>
            <div className="card-hd">
              <div className="card-ico">⚙️</div>
              <div>
                <div className="card-step mono">STEP 02</div>
                <div className="card-title">选择处理操作</div>
              </div>
            </div>
            <div className="modes">
              {([
                { key: 'cut',            ico: '✂️', lbl: '静音裁切',  desc: '自动检测并移除长时间停顿，输出更紧凑',  cli: '--cut' },
                { key: 'auto_volume',    ico: '🔊', lbl: '音量均衡',  desc: '响度标准化到 -16 LUFS，统一音量',       cli: '--auto-volume' },
                { key: 'enhance_speech', ico: '🎙', lbl: '语音增强',  desc: 'AI 降噪处理，过滤噪音提升人声清晰度',   cli: '--enhance-speech' },
                { key: 'subtitle',       ico: '📝', lbl: '生成字幕',  desc: 'FunASR 语音转文字，支持多语言嵌入',     cli: '--subtitle' },
              ] as const).map(({ key, ico, lbl, desc, cli }) => (
                <div key={key} className={`mode ${cfg[key] ? 'mode--on' : ''}`}
                  onClick={() => set(key, !cfg[key])}>
                  <span className="mode-ico">{ico}</span>
                  <div className="mode-body">
                    <span className="mode-lbl">{lbl}</span>
                    <span className="mode-desc">{desc}</span>
                  </div>
                  <span className="mode-cli mono">{cli}</span>
                  <Toggle on={cfg[key]} onChange={v => set(key, v)} />
                </div>
              ))}
            </div>
          </section>

          {/* STEP 03: Basic config — only when cut or subtitle is active */}
          {showStep03 && (
            <section className="card" style={{ animation: 'fadeUp 0.3s ease both' }}>
              <div className="card-hd">
                <div className="card-ico">🎛</div>
                <div>
                  <div className="card-step mono">STEP 03</div>
                  <div className="card-title">基础配置</div>
                </div>
              </div>
              <div className="card-bd">
                <div className="basic-cfg">

                  {/* Aggressiveness — only when cut */}
                  {cfg.cut && (
                    <Field label="裁切激进度">
                      <select className="inp" value={cfg.aggressiveness}
                        onChange={e => set('aggressiveness', e.target.value)}>
                        <option value="natural">natural — 保守，保留更多自然停顿</option>
                        <option value="balanced">balanced — 均衡（推荐）</option>
                        <option value="dense">dense — 激进，大量裁切停顿</option>
                      </select>
                    </Field>
                  )}

                  {/* Subtitle language — only when subtitle */}
                  {cfg.subtitle && (
                    <Field label="字幕语言">
                      <select className="inp" value={cfg.subtitle_language}
                        onChange={e => set('subtitle_language', e.target.value)}>
                        {LANGUAGES.map(({ v, l }) => (
                          <option key={v} value={v}>{l}</option>
                        ))}
                      </select>
                    </Field>
                  )}

                  {/* Subtitle embed mode — only when subtitle */}
                  {cfg.subtitle && (
                    <Field label="字幕输出形式">
                      <EmbedModeGroup
                        value={cfg.subtitle_embed_mode}
                        onChange={v => set('subtitle_embed_mode', v)}
                        audioFile={audioFile}
                      />
                      {audioFile && (
                        <p className="field-note mono">音频文件仅支持输出独立字幕文件</p>
                      )}
                    </Field>
                  )}

                </div>
              </div>
            </section>
          )}

          {/* Advanced config */}
          {anyMode && (
            <section className="card" style={{ animation: 'fadeUp 0.45s 0.28s ease both' }}>
              <button className="adv-btn" onClick={() => setShowAdv(v => !v)}>
                <span>高级配置</span>
                <span className="mono" style={{ fontSize: '0.78rem', color: 'var(--muted)' }}>细节参数</span>
                <span className={`adv-arrow ${showAdv ? 'adv-arrow--open' : ''}`}>▾</span>
              </button>

              {showAdv && (
                <div className="adv-body" style={{ animation: 'fadeUp 0.18s ease' }}>

                  {/* Cut advanced */}
                  {cfg.cut && (
                    <div className="adv-sect">
                      <div className="adv-tag mono">裁切参数</div>
                      <div className="fg fg3">
                        {(['min_silence_ms', 'padding_ms', 'crossfade_ms'] as const).map((k, i) => (
                          <Field key={k} label={['最短静音 (ms)', '首尾留白 (ms)', '交叉淡化 (ms)'][i]}>
                            <input className="inp" type="number" min={0}
                              placeholder="默认" value={cfg[k]}
                              onChange={e => set(k, e.target.value)} />
                          </Field>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Auto volume advanced */}
                  {cfg.auto_volume && (
                    <div className="adv-sect">
                      <div className="adv-tag mono">响度目标</div>
                      <div style={{ maxWidth: 180 }}>
                        <Field label="Target LUFS">
                          <input className="inp" type="number" step={0.1}
                            placeholder="-16.0" value={cfg.target_lufs}
                            onChange={e => set('target_lufs', e.target.value)} />
                        </Field>
                      </div>
                    </div>
                  )}

                  {/* Enhance advanced */}
                  {cfg.enhance_speech && (
                    <div className="adv-sect">
                      <div className="adv-tag mono">增强参数</div>
                      <div className="fg fg2">
                        <Field label="增强后端">
                          <select className="inp" value={cfg.enhancer_backend}
                            onChange={e => set('enhancer_backend', e.target.value)}>
                            {['deepfilternet3', 'metricgan-plus', 'demucs-vocals', 'resemble-enhance'].map(v => (
                              <option key={v}>{v}</option>
                            ))}
                          </select>
                        </Field>
                        <Field label="增强强度">
                          <select className="inp" value={cfg.enhancer_profile}
                            onChange={e => set('enhancer_profile', e.target.value)}>
                            {['natural', 'strong'].map(v => <option key={v}>{v}</option>)}
                          </select>
                        </Field>
                        <Field label="失败回退">
                          <select className="inp" value={cfg.enhancer_fallback}
                            onChange={e => set('enhancer_fallback', e.target.value)}>
                            {['fail', 'original', 'deepfilternet3', 'metricgan-plus'].map(v => (
                              <option key={v}>{v}</option>
                            ))}
                          </select>
                        </Field>
                        <Field label="模型目录">
                          <input className="inp" type="text"
                            placeholder="留空使用默认缓存目录" value={cfg.model_path}
                            onChange={e => set('model_path', e.target.value)} />
                        </Field>
                      </div>
                    </div>
                  )}

                  {/* Subtitle advanced — only format + max_chars remain here */}
                  {cfg.subtitle && (
                    <div className="adv-sect">
                      <div className="adv-tag mono">字幕参数</div>
                      <div className="fg fg2" style={{ maxWidth: 360 }}>
                        <Field label="字幕文件格式">
                          <select className="inp" value={cfg.subtitle_format}
                            onChange={e => set('subtitle_format', e.target.value)}>
                            {['srt', 'vtt'].map(v => <option key={v}>{v}</option>)}
                          </select>
                        </Field>
                        <Field label="单条最大字符数">
                          <input className="inp" type="number" min={0}
                            value={cfg.subtitle_max_chars}
                            onChange={e => set('subtitle_max_chars', e.target.value)} />
                        </Field>
                      </div>
                    </div>
                  )}

                  <div className="adv-sep" />

                  <label className="chk-row">
                    <input type="checkbox" checked={cfg.keep_temp}
                      onChange={e => set('keep_temp', e.target.checked)} />
                    <div>
                      <div className="chk-lbl">保留临时文件</div>
                      <div className="chk-desc">调试时使用，会占用额外磁盘空间</div>
                    </div>
                  </label>
                </div>
              )}
            </section>
          )}

          {/* Submit */}
          <div className="submit" style={{ animation: 'fadeUp 0.45s 0.34s ease both' }}>
            <p className="submit-note">
              处理异步执行，提交后页面自动轮询状态。<br />
              大文件或启用语音增强时可能需要数分钟，请耐心等待。
            </p>
            <button
              className="btn-run"
              disabled={!file || appState === 'processing'}
              onClick={handleSubmit}
            >
              <svg width="17" height="17" viewBox="0 0 24 24" fill="none">
                <polygon points="5,3 19,12 5,21" fill="currentColor" />
              </svg>
              开始处理
            </button>
          </div>

        </div>{/* end form */}
      </main>
    </div>
  )
}
