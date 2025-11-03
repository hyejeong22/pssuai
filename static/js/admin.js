const state = {
  access: { page: 1, rows: [], pageSize: 15 },
  qr: { page: 1, rows: [], pageSize: 15 },
}

function qs(sel) {
  return document.querySelector(sel)
}
function qsa(sel) {
  return [...document.querySelectorAll(sel)]
}

// 유틸: ISO 문자열 -> "YYYY-MM-DD HH:MM:SS" 로, 타임존 꼬리(+09:00) 제거
function toDateTime(s) {
  if (!s) return ''
  return s.replace('T', ' ').replace(/([+-]\d{2}:\d{2}|Z)$/, '')
}

// 최근 1달 기록 보기
function formatLocalISO(date) {
  const y = date.getFullYear()
  const m = (date.getMonth() + 1).toString().padStart(2, '0')
  const d = date.getDate().toString().padStart(2, '0')
  return `${y}-${m}-${d}`
}

document.addEventListener('DOMContentLoaded', () => {
  // 탭 전환
  qsa('.tab').forEach((btn) => {
    btn.addEventListener('click', () => {
      qsa('.tab').forEach((b) => b.classList.remove('active'))
      btn.classList.add('active')
      const which = btn.dataset.tab
      qsa('.panel').forEach((p) => p.classList.remove('active'))
      qs(`#panel-${which}`).classList.add('active')
      // 공용 필터는 access/qr에서만 사용, residents에서는 숨김
      qs('#filters-global').classList.toggle('hidden', which === 'residents')
      // 첫 로딩 시 데이터 없으면 로드
      if (which === 'access' && state.access.rows.length === 0) loadAccess()
      if (which === 'qr' && state.qr.rows.length === 0) loadQR()

      if (which === 'access') render('access')
      else if (which === 'qr') render('qr')

      try {
        whenTabOpened(which)
      } catch (_) {}
    })
  })

  // 날짜 기본값 (30일 전 - 오늘)
  const today = new Date()
  const thirtyDaysAgo = new Date(today)
  thirtyDaysAgo.setDate(today.getDate() - 30)

  const todayStr = formatLocalISO(today)
  const thirtyDaysAgoStr = formatLocalISO(thirtyDaysAgo)

  qs('#dateFrom').value = thirtyDaysAgoStr
  qs('#dateTo').value = todayStr

  // 새로고침 버튼
  qs('#btn-refresh').addEventListener('click', () => {
    const activeTab = qs('.tab.active').dataset.tab
    if (activeTab === 'access') loadAccess()
    else if (activeTab === 'qr') loadQR()
    else if (activeTab === 'residents') reloadResidents()
  })

  // 페이저
  qsa('.pager .prev').forEach((b) =>
    b.addEventListener('click', () => {
      const tgt = b.dataset.target
      if (state[tgt].page > 1) {
        state[tgt].page--
        render(tgt)
      }
    })
  )
  qsa('.pager .next').forEach((b) =>
    b.addEventListener('click', () => {
      const tgt = b.dataset.target
      const total = filteredRows(tgt).length
      const maxPage = Math.max(1, Math.ceil(total / state[tgt].pageSize))
      if (state[tgt].page < maxPage) {
        state[tgt].page++
        render(tgt)
      }
    })
  )

  // 초기 탭 로드: access
  // 초기 탭 로드: access
  loadAccess()
  // access는 필터 사용
  qs('#filters-global').classList.remove('hidden')
})

// 공통 필터
function filteredRows(which) {
  const kw = qs('#kw').value.trim().toLowerCase()
  const from = qs('#dateFrom').value
  const to = qs('#dateTo').value
  const rows = state[which].rows

  return rows.filter((r) => {
    // 키워드: 이름/전화/동-호/QR
    const blob = JSON.stringify(r).toLowerCase()
    const passKw = !kw || blob.includes(kw)

    // 날짜: event_time이 YYYY-MM-DD 기반 비교
    const t = (r.event_time || '').slice(0, 10)
    const passFrom = !from || t >= from
    const passTo = !to || t <= to

    return passKw && passFrom && passTo
  })
}

function render(which) {
  const tbl = which === 'access' ? qs('#tbl-access tbody') : qs('#tbl-qr tbody')
  const page = state[which].page
  const ps = state[which].pageSize

  const rows = filteredRows(which)
  const total = rows.length
  const maxPage = Math.max(1, Math.ceil(total / ps))
  state[which].page = Math.min(page, maxPage)

  const start = (state[which].page - 1) * ps
  const slice = rows.slice(start, start + ps)

  tbl.innerHTML = slice
    .map((r) => {
      if (which === 'access') {
        return `
        <tr>
          <td>${r.id ?? ''}</td>
          <td>${r.device_id ?? ''}</td>
          <td>${r.images_dir ?? ''}</td>
          <td>${r.event_time ?? ''}</td>
        </tr>`
      } else {
        return `
        <tr>
          <td>${r.id ?? ''}</td>
          <td>${r.phone ?? ''}</td>
          <td>${r.purpose ?? ''}</td>
          <td>${r.status ?? ''}</td>
          <td>${r.device_id ?? ''}</td>
          <td>${r.event_time ?? ''}</td>
        </tr>`
      }
    })
    .join('')

  if (slice.length === 0) {
    const colspan = which === 'access' ? 4 : 6
    tbl.innerHTML = `<tr><td colspan="${colspan}" style="color:#9aa7d8;padding:16px;">
      표시할 데이터가 없습니다. (검색/날짜 필터 확인)
    </td></tr>`
  }

  qs(
    `.pager .page[data-target="${which}"]`
  ).textContent = `${state[which].page} / ${maxPage}`
}

async function loadAccess() {
  try {
    const res = await fetch('/api/access-events')
    const json = await res.json()
    if (!json.ok) {
    }

    const arr =
      json.rows && json.rows.access_events
        ? json.rows.access_events
        : json.rows || []
    state.access.rows = normalizeAccess(arr)
    state.access.page = 1
    render('access')
  } catch (e) {
    alert('세대주 출입기록 로드 실패: ' + e.message)
  }
}

async function loadQR() {
  try {
    const res = await fetch('/api/qr-events')
    const json = await res.json()
    if (!json.ok) {
    }
    const arr =
      json.rows && json.rows.qr_events ? json.rows.qr_events : json.rows || []
    state.qr.rows = normalizeQR(arr)
    state.qr.page = 1
    render('qr')
  } catch (e) {
    alert('방문자 QR 기록 로드 실패: ' + e.message)
  }
}

function normalizeAccess(rows) {
  return rows.map((r) => ({
    id: r.id ?? null,
    device_id: r.device_id ?? '',
    images_dir: r.images_dir ?? '',
    event_time: toDateTime(r.requested_at ?? r.event_time ?? r.timestamp),
  }))
}

function normalizeQR(rows) {
  return rows.map((r) => ({
    id: r.id ?? null,
    phone: r.phone ?? '',
    purpose: r.purpose ?? '',
    status: r.status ?? '',
    device_id: r.device_id ?? '',
    event_time: toDateTime(r.requested_at ?? r.event_time ?? r.timestamp),
  }))
}

/* ================================
   세대주 목록 — GET + DELETE
================================ */
const RES_LIST_API = '/external/residents'
const RES_ITEM_API = (id) => `/external/residents/${id}`

let _residentsAll = [] // 원본
let _residentsView = [] // 필터링 뷰

async function reloadResidents() {
  try {
    const res = await fetch(RES_LIST_API)
    if (!res.ok) throw new Error(`서버 오류\n${await res.text()}`)

    const data = await res.json()

    // ✅ 수정: registrations 배열이 있으면 그걸 사용
    const list = Array.isArray(data)
      ? data
      : data.registrations || data.items || data.data || []

    _residentsAll = list
    _residentsView = _residentsAll.slice()
    renderResidents(_residentsView)
  } catch (e) {
    console.error(e)
    alert('세대주 목록을 불러오지 못했습니다.\n' + (e.message || ''))
  }
}

function renderResidents(rows) {
  const $body = document.getElementById('residents-tbody')
  const $count = document.getElementById('residentCount')
  const $empty = document.getElementById('residentEmpty')

  if (!$body) {
    console.warn('residents-tbody not found')
    return
  }
  $body.innerHTML = ''

  if (!rows || rows.length === 0) {
    $body.innerHTML = ''
    if ($count) $count.textContent = '0건'
    if ($empty) $empty.style.display = 'block'
    return
  }

  const html = rows
    .map((r) => {
      const id = r.id ?? ''
      const name = r.name ?? ''
      const phone = r.phone ?? r.tel ?? ''
      const unit = (r.unit ?? `${r.dong ?? ''}-${r.ho ?? ''}`).replace(
        /^-|-$/g,
        ''
      )
      const cAt = (r.created_at || r.requested_at || r.approved_at || '')
        .toString()
        .replace('T', ' ')

      return `
      <tr>
        <td>${id}</td>
        <td>${escapeHtml(name)}</td>
        <td>${escapeHtml(phone)}</td>
        <td>${escapeHtml(unit)}</td>
        <td>${escapeHtml(cAt)}</td>
        <td>
          <button class="danger small" onclick="deleteResident(${id})">삭제</button>
        </td>
      </tr>
    `
    })
    .join('')

  $body.innerHTML = html
  $count.textContent = `${rows.length}건`
  if ($empty) $empty.style.display = 'none'
}

function filterResidents() {
  const q = (document.getElementById('residentSearch').value || '')
    .trim()
    .toLowerCase()
  if (!q) {
    _residentsView = _residentsAll.slice()
  } else {
    _residentsView = _residentsAll.filter((r) => {
      const name = (r.name ?? '').toLowerCase()
      const phone = (r.phone ?? r.tel ?? '').toLowerCase()
      const unit = (r.unit ?? r.unit_number ?? '').toLowerCase()
      return name.includes(q) || phone.includes(q) || unit.includes(q)
    })
  }
  renderResidents(_residentsView)
}

async function deleteResident(id) {
  if (!confirm('정말 삭제하시겠습니까?')) return

  try {
    const res = await fetch(`/admin/residents/${id}`, { method: 'DELETE' })
    const json = await res.json()

    if (res.ok && json.ok) {
      alert('✅ 삭제 완료')
      reloadResidents() // 목록 새로고침 함수
    } else {
      alert('❌ 삭제 실패: ' + (json.error || '서버 오류'))
    }
  } catch (err) {
    console.error(err)
    alert('⚠️ 서버 연결 오류')
  }
}

/* 유틸: XSS 방지 간단 이스케이프 */
function escapeHtml(s) {
  return String(s)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;')
}
/* 탭 진입 시 자동 로딩 */
function whenTabOpened(which) {
  if (which === 'residents') {
    // 이미 불러왔으면 재요청 안 하고, 비어있을 때만 로드
    if (_residentsAll.length === 0) {
      reloadResidents()
    }
  }
}
