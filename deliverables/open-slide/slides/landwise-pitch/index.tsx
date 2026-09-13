import type { CSSProperties, ReactNode } from 'react';
import { useSlidePageNumber, type DesignSystem, type Page, type SlideMeta, type SlideTransition } from '@open-slide/core';
import reviewWorkspace from './assets/review-workspace.png';
import roadCheck from './assets/road-check.png';

export const design: DesignSystem = {
  palette: { bg: '#F4F2E9', text: '#183F37', accent: '#B88A41' },
  fonts: {
    display: '"PingFang TC", "Microsoft JhengHei", sans-serif',
    body: '"PingFang TC", "Microsoft JhengHei", sans-serif',
  },
  typeScale: { hero: 172, body: 36 },
  radius: 0,
};

const muted = '#5D7167';
const line = '#C8D0C3';
const pale = '#C7D7CA';
const gold = 'var(--osd-accent)';
const ink = 'var(--osd-text)';
const paper = 'var(--osd-bg)';

function Footer({ dark = false, source }: { dark?: boolean; source?: string }) {
  const { current, total } = useSlidePageNumber();
  return (
    <footer style={{ position: 'absolute', left: 120, right: 120, bottom: 46, borderTop: `1px solid ${dark ? '#526D5F' : line}`, paddingTop: 20, display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 22, color: dark ? pale : muted }}>
      <span>沒有錯的地方 LANDWISE{source ? `　／　${source}` : '　／　AI 輔助估價審查'}</span>
      <span style={{ fontVariantNumeric: 'tabular-nums', letterSpacing: 3 }}>{String(current).padStart(2, '0')} / {String(total).padStart(2, '0')}</span>
    </footer>
  );
}

function Canvas({ children, dark = false, source }: { children: ReactNode; dark?: boolean; source?: string }) {
  return <section data-landwise-page style={{ width: '100%', height: '100%', position: 'relative', boxSizing: 'border-box', background: dark ? ink : paper, color: dark ? paper : ink, fontFamily: 'var(--osd-font-body)' }}>
    {children}<Footer dark={dark} source={source} />
  </section>;
}

function Header({ eyebrow, title, dark = false }: { eyebrow: string; title: string; dark?: boolean }) {
  return <header style={{ position: 'absolute', left: 120, top: 100, right: 120 }}>
    <div style={{ color: dark ? pale : muted, fontSize: 25, letterSpacing: 4, fontWeight: 600 }}>{eyebrow}</div>
    <h2 style={{ margin: '24px 0 0', fontFamily: 'var(--osd-font-display)', fontSize: 76, lineHeight: 1.2, fontWeight: 700, letterSpacing: -2, whiteSpace: 'nowrap' }}>{title}</h2>
  </header>;
}

function Placed({ children, left = 120, top, width = 1680, style }: { children: ReactNode; left?: number; top: number; width?: number; style?: CSSProperties }) {
  return <div style={{ position: 'absolute', left, top, width, ...style }}>{children}</div>;
}

function Body({ children, light = false, style }: { children: ReactNode; light?: boolean; style?: CSSProperties }) {
  return <p style={{ margin: 0, fontSize: 'var(--osd-size-body)', lineHeight: 1.55, color: light ? pale : muted, ...style }}>{children}</p>;
}

function Issue({ number, title, detail, top }: { number: string; title: string; detail: string; top: number }) {
  return <Placed top={top} style={{ display: 'grid', gridTemplateColumns: '120px 510px 1fr', alignItems: 'center', borderTop: `1px solid ${line}`, paddingTop: 34 }}>
    <span style={{ color: gold, fontSize: 52, fontFamily: 'Georgia, serif' }}>{number}</span>
    <h3 style={{ fontSize: 44, fontWeight: 600, margin: 0 }}>{title}</h3>
    <Body>{detail}</Body>
  </Placed>;
}

function ProcessStage({ number, title, detail, left }: { number: string; title: string; detail: ReactNode; left: number }) {
  return <Placed left={left} top={370} width={355}>
    <div style={{ color: gold, fontFamily: 'Georgia, serif', fontSize: 82, lineHeight: 1 }}>{number}</div>
    <h3 style={{ fontSize: 44, margin: '34px 0 24px', fontWeight: 600 }}>{title}</h3>
    <Body>{detail}</Body>
  </Placed>;
}

function Role({ label, title, children, left }: { label: string; title: string; children: ReactNode; left: number }) {
  return <Placed left={left} top={360} width={480}>
    <div style={{ color: gold, fontSize: 26, letterSpacing: 3 }}>{label}</div>
    <h3 style={{ fontSize: 56, margin: '28px 0 34px', lineHeight: 1.2, fontWeight: 600 }}>{title}</h3>
    <Body light>{children}</Body>
  </Placed>;
}

const Cover: Page = () => <Canvas dark>
  <Placed top={116}><div style={{ fontSize: 26, letterSpacing: 5, color: pale }}>新北市政府 AI 黑客松　／　競賽提案</div></Placed>
  <Placed top={290}>
    <div style={{ display: 'flex', alignItems: 'baseline', gap: 48 }}>
      <h1 style={{ fontSize: 'var(--osd-size-hero)', lineHeight: 1.08, margin: 0, fontWeight: 700, letterSpacing: 8 }}>沒有錯的地方</h1>
      <span style={{ fontFamily: 'Georgia, serif', fontSize: 72, color: pale, letterSpacing: 5 }}>LANDWISE</span>
    </div>
    <p style={{ fontSize: 70, margin: '55px 0 0', lineHeight: 1.3, fontWeight: 500 }}>讓估價審查，有依據、可追溯。</p>
  </Placed>
  <Placed top={782}><Body light>AI 整理文件　／　程式核對數字　／　人員做出判斷</Body></Placed>
</Canvas>;

const Problem: Page = () => <Canvas source="專案命題整理：docs/TODO.md">
  <Header eyebrow="THE PROBLEM　／　審查現場" title="一個數字，要跨多少張表核對？" />
  <Issue number="01" title="條件與數字散落各表" detail="查條件、查級距，再比對明細與合計。" top={335} />
  <Issue number="02" title="相似基準，不一定適用" detail="地區、用地、日期與版本，都要對得上。" top={510} />
  <Issue number="03" title="有差異，還要找回依據" detail="審查人員需要原文、判定理由與修訂紀錄。" top={685} />
</Canvas>;

const Workflow: Page = () => <Canvas source="README.md；docs/architecture.md">
  <Header eyebrow="THE SOLUTION　／　一條可操作的流程" title="從文件到問題清單，再到審查成果。" />
  <Placed top={332} style={{ borderTop: `2px solid ${line}` }}><span /></Placed>
  <ProcessStage number="01" title="建立基準" detail={<>上傳評價基準<br />核對後保存版本</>} left={120} />
  <ProcessStage number="02" title="整理文件" detail={<>本機 OCR 辨識<br />AI 協助欄位草稿</>} left={550} />
  <ProcessStage number="03" title="核對差異" detail={<>人工確認條件<br />程式重算與跨表檢查</>} left={980} />
  <ProcessStage number="04" title="保存成果" detail={<>保留修訂快照<br />匯出審查 Excel</>} left={1410} />
  <Placed top={824}><Body style={{ color: ink, fontSize: 38 }}>每一步，都帶著來源、基準版本與待確認狀態。</Body></Placed>
</Canvas>;

const Responsibilities: Page = () => <Canvas dark source="docs/architecture.md；docs/agentic-rag.md">
  <Header eyebrow="THE DESIGN　／　可信任的分工" title="AI 整理、程式計算、人員確認。" dark />
  <Role label="AI ASSISTANCE" title="整理與說明" left={120}>Bedrock 產生欄位草稿<br />依檢索來源生成引用說明<br />Agent 呼叫已註冊工具</Role>
  <Role label="DETERMINISTIC ENGINE" title="規則與運算" left={710}>查級距與修正矩陣<br />Decimal 加總、跨表檢核<br />回傳原始審查結果</Role>
  <Role label="HUMAN REVIEW" title="專業與責任" left={1300}>確認適用基準與原文<br />處理特殊情況與缺值<br />採用修正並保存版本</Role>
  <Placed top={822} style={{ borderTop: '1px solid #526D5F', paddingTop: 28 }}><Body light>模型說明有疑點時，已完成的程式審查仍可呈現。</Body></Placed>
</Canvas>;

const Example: Page = () => <Canvas source="app/domain/sample.py；本次本機示範截圖">
  <Header eyebrow="THE DEMO　／　道路寬度差異" title="原填 +2%，依基準查出 +5%。" />
  <Placed top={340} width={660}>
    <Body>比準地 18 m → 稍優<br />比較標的 6 m → 稍劣</Body>
    <div style={{ fontSize: 160, lineHeight: 1.15, color: ink, fontFamily: 'Georgia, serif', marginTop: 36 }}>+5<span style={{ fontSize: 100 }}>%</span></div>
    <Body style={{ marginTop: 30 }}>由案件指定版本的矩陣查得</Body>
  </Placed>
  <Placed left={890} top={345} width={910}>
    <img src={roadCheck} alt="實際道路寬度檢核：原填 2%，基準 5%；提供原文、基準與採用建議" style={{ width: 910, height: 360, objectFit: 'contain', objectPosition: 'left top', display: 'block' }} />
    <Body style={{ marginTop: 28, fontSize: 32 }}>查看原文與基準 → 採用建議 → 再次確認</Body>
  </Placed>
  <Placed top={855}><Body style={{ fontSize: 28 }}>人工植入錯誤的範例；修正率僅適用該基準版本，非通用估價規則。</Body></Placed>
</Canvas>;

const Evidence: Page = () => <Canvas source="docs/rag.md；docs/agentic-rag.md">
  <Header eyebrow="GROUNDED ANSWERS　／　有來源的說明" title="問「為什麼」，也能回到原始依據。" />
  <Placed top={340}><p style={{ fontSize: 58, lineHeight: 1.35, margin: 0, color: ink }}>「這個修正率的依據是什麼？」</p></Placed>
  <Placed top={505} width={740}>
    <div style={{ color: gold, fontSize: 26, letterSpacing: 2, marginBottom: 22 }}>先找適用來源</div>
    <Body>以基準版本、地區、用地及日期篩選。<br />Agent 可搜尋、讀頁、查規則與呼叫審查。</Body>
  </Placed>
  <Placed left={1020} top={505} width={780}>
    <div style={{ color: gold, fontSize: 26, letterSpacing: 2, marginBottom: 22 }}>再提供引用說明</div>
    <Body>保留文件、頁碼、原文與版本。<br />找不到來源或引用無效，顯示依據不足。</Body>
  </Placed>
  <Placed top={813} style={{ borderTop: `1px solid ${line}`, paddingTop: 28 }}><Body style={{ color: ink }}>查詢不修改案件；引用存在，仍須核對語意與欄位方向。</Body></Placed>
</Canvas>;

const Product: Page = () => <Canvas source="本次本機介面截圖；docs/form-exports.md">
  <Header eyebrow="WORKING PRODUCT　／　實際審查工作台" title="看見差異，也看見下一步。" />
  <Placed top={330} width={990}>
    <img src={reviewWorkspace} alt="最新版估價審查工作台，顯示人工植入錯誤的範例與審查結果" style={{ width: 990, height: 595, objectFit: 'contain', objectPosition: 'left top', display: 'block' }} />
  </Placed>
  <Placed left={1240} top={345} width={560}>
    <h3 style={{ margin: '0 0 18px', fontSize: 42, fontWeight: 600 }}>從問題開始</h3>
    <Body style={{ fontSize: 32 }}>篩選疑似錯誤<br />查看原文與基準</Body>
    <h3 style={{ margin: '40px 0 18px', fontSize: 42, fontWeight: 600 }}>修改可回查</h3>
    <Body style={{ fontSize: 32 }}>保存版本與修訂快照<br />匯出同版審查 Excel</Body>
    <p style={{ margin: '38px 0 0', fontSize: 25, lineHeight: 1.5, color: muted }}>畫面為內建錯誤示範；<br />未處理的疑點仍會保留。</p>
  </Placed>
</Canvas>;

const Validation: Page = () => <Canvas dark source="既有驗收紀錄：docs/agent-evaluation.md，2026-09-13">
  <Header eyebrow="EVIDENCE　／　驗證到哪裡" title="可重跑的測試，是目前的交付證據。" dark />
  <Placed top={385} width={500}>
    <div style={{ fontSize: 142, lineHeight: 1, fontFamily: 'Georgia, serif' }}>1,178</div>
    <h3 style={{ margin: '34px 0 20px', fontSize: 40, fontWeight: 500 }}>Python 測試通過</h3>
    <Body light style={{ fontSize: 32 }}>另有 4 項跳過</Body>
  </Placed>
  <Placed left={745} top={385} width={440}>
    <div style={{ fontSize: 142, lineHeight: 1, fontFamily: 'Georgia, serif' }}>11</div>
    <h3 style={{ margin: '34px 0 20px', fontSize: 40, fontWeight: 500 }}>Chrome 流程測試</h3>
    <Body light style={{ fontSize: 32 }}>已記錄的 E2E 通過結果</Body>
  </Placed>
  <Placed left={1340} top={385} width={460}>
    <div style={{ fontSize: 142, lineHeight: 1, fontFamily: 'Georgia, serif', color: '#DFC087' }}>6/6</div>
    <h3 style={{ margin: '34px 0 20px', fontSize: 40, fontWeight: 500 }}>Bedrock 合成驗收</h3>
    <Body light style={{ fontSize: 32 }}>涵蓋缺來源、錯版本與缺值</Body>
  </Placed>
  <Placed top={813} style={{ borderTop: '1px solid #526D5F', paddingTop: 28 }}><Body light style={{ fontSize: 31 }}>以上為 9/13 既有紀錄，非本次重跑；六題 smoke 驗收不等於整體準確率。</Body></Placed>
</Canvas>;

const Scope: Page = () => <Canvas source="README.md；docs/TODO.md；docs/form-exports.md">
  <Header eyebrow="DELIVERY SCOPE　／　完成度與下一階段" title="已有可操作 MVP，擴充範圍清楚。" />
  <Placed top={345} width={770}>
    <h3 style={{ fontSize: 46, margin: '0 0 34px', fontWeight: 600 }}>目前可展示</h3>
    <Body>同類版型基準匯入與版本管理<br /><br />本機 OCR、單一比較標的審查<br /><br />引用問答、修訂保存與 Excel 匯出</Body>
  </Placed>
  <Placed left={1030} top={345} width={770}>
    <h3 style={{ fontSize: 46, margin: '0 0 34px', fontWeight: 600, color: '#8D692D' }}>下一階段驗證</h3>
    <Body>住宅規則與多標的全流程整合<br /><br />不同版型與完整計算追溯<br /><br />帳號權限、備份及正式審核流程</Body>
  </Placed>
  <Placed top={845}><Body style={{ fontSize: 28 }}>現行案件仍為單一比較標的；完整審查 Excel 與固定模板分表的適用範圍不同。</Body></Placed>
</Canvas>;

const Closing: Page = () => <Canvas dark>
  <Placed top={115}><div style={{ color: pale, fontSize: 26, letterSpacing: 4 }}>NEXT STEP　／　與承辦共同試辦</div></Placed>
  <Placed top={245}>
    <h2 style={{ fontSize: 96, lineHeight: 1.3, margin: 0, fontWeight: 600, letterSpacing: -3 }}>把時間留給<br />需要專業判斷的地方。</h2>
  </Placed>
  <Placed top={596}><Body light style={{ fontSize: 38 }}>以同一批合適案件，對照純人工與系統輔助審查。</Body></Placed>
  <Placed top={711} style={{ borderTop: '1px solid #526D5F', paddingTop: 32 }}>
    <div style={{ display: 'flex', gap: 105, fontSize: 40 }}><span>量測總工時</span><span>追蹤漏檢與誤報</span><span>確認待辦處理成本</span></div>
  </Placed>
  <Placed top={853}><Body light style={{ fontSize: 29 }}>邀請提供：適用測試案件、經確認的基準、承辦與估價專業人員。效益尚待實測。</Body></Placed>
</Canvas>;

export const notes = [
  '建議 45 秒。各位委員好，我們的作品是沒有錯的地方 Landwise，一套 AI 輔助估價審查工作台。它將文件、基準與計算核對放在同一個流程，讓承辦人員能看出差異、回到來源並保留修訂。今天介紹目前可操作的 MVP，而不是宣稱已自動完成所有估價案件。整份簡報約 8–10 分鐘。依據：README.md、docs/architecture.md。',
  '建議 50 秒。審查涉及三種反覆工作：先看土地條件，再查適用基準，最後核對各表數字是否一致。即使加總算對，也可能查錯級距或引用錯誤版本。找到差異後，承辦仍要翻回來源確認理由。這是本專案要減輕的重複核對工作；目前沒有人工耗時基線，不在此宣稱任何節省比例。依據：docs/TODO.md 的命題與差距、README.md。',
  '建議 65 秒。先上傳同類版型的評價基準表，人工核對期間及矩陣方向後，保存不可覆寫版本。選定基準再上傳題目，PDF 經本機 PaddleOCR 或 RapidOCR CPU 辨識，保留文字及座標；若啟用 Bedrock，可以另外請 AI 整理欄位草稿。人員核對後，規則引擎查級距、矩陣、加總與跨表一致性，再保存與匯出。目前主要輸出為完整審查 Excel，另有 CSV、JSON、HTML 與固定版型分表。案件 PDF 產製已移除，不能宣稱提供後端 PDF 報告。依據：README.md、docs/architecture.md、docs/form-exports.md。',
  '建議 60 秒。三者分工是設計核心。Bedrock 做欄位草稿及引用說明；Agent 可以呼叫白名單中的唯讀工具，但實際查表與算術由 domain 的確定性程式執行。計算內部使用 Decimal，現行部分資料模型仍有 float，所以不宣稱已完成全資料模型的 Decimal 遷移。人員負責適用基準、原文與特殊情況。AI 草稿預覽不修改案件，套用後仍需確認；依據查詢也不寫入案件。模型最後說明失敗時，已完成的引擎審查仍會保留。依據：docs/architecture.md、docs/agentic-rag.md、docs/TODO.md。',
  '建議 65 秒。這是本次從目前程式擷取的真實介面，資料來自人工整理範例，並刻意將道路修正率從百分之五改成百分之二。比準地道路十八公尺為稍優，比較標的六公尺為稍劣，查案件綁定矩陣交會處得到百分之五。使用者可以查看基準頁碼，再決定是否採用建議。採用後須再次人工確認。這是人工植入錯誤的展示，不是真實案件抓錯成果；百分之五也只適用此基準版本。截圖使用獨立暫存資料庫及關閉 Bedrock 的本機服務，未修改既有案件。依據：app/domain/sample.py、app/domain/rules.py 及本次截圖。',
  '建議 60 秒。依據問答先以案件的基準版本、地區、用地與期間選出適用文件，再做文字檢索與附引用說明。Agent 的四個唯讀工具是搜尋、讀頁、查規則與程式審查。引用檢查會核對文件、頁碼與原文；無來源、版本不符或引用無效時，系統會回報依據不足，不以模型推測取代文件。引用存在不代表語意或左右欄一定正確，仍需人工核對。目前是中文文字檢索，尚非向量或 GraphRAG。依據：docs/rag.md、docs/agentic-rag.md。',
  '建議 55 秒。這是目前分支的實際工作台截圖，展示人工植入的錯誤。承辦先篩選疑似錯誤，再查看原文、基準與原填值。儲存會留下 revision 和修訂快照；舊畫面版本衝突時拒絕覆寫。Excel 輸出取自已儲存案件版本，審核明細另列預期值與狀態，不自動採用修正。這不是防竄改稽核或正式簽章；也沒有宣稱所有欄位都已具備完整計算追溯。依據：docs/architecture.md、docs/form-exports.md。',
  '建議 65 秒。數字引用 2026 年 9 月 13 日已提交的驗收文件，不是製作本簡報時重新執行的測試。Python 為 1,178 passed、4 skipped；Chrome E2E 為 11 passed。真實 Bedrock 使用合成文件六題，修正後六題通過，涵蓋工具、缺來源、錯版本、缺值、矛盾來源與有根據回答。六題是固定 smoke 測試，不是泛化準確率；也沒有測量真實 OCR 品質或工時效益。文件另保留現場問題仍可能產生無效引用的紀錄，系統會回傳 insufficient_evidence 並保留程式審查，不能宣稱模型永不出錯。依據：docs/agent-evaluation.md、docs/evaluations/agent-source-fix-2026-09-13.json。',
  '建議 60 秒。已完成同類表格結構的動態基準匯入、OCR、單一比較標的審查、引用問答、版本保存與 Excel。樹林住宅純領域計算已有獨立實作，但尚未接到現行 Case 與應用流程；三標的完整題目也仍待整合。完整審查 Excel 支援動態因素，固定官方表3、表4、表5仍有既有欄位與用地限制。正式部署還需權限、備份與審核流程。AWS 競賽單機環境已有部署紀錄，但不代表正式營運等級上線。依據：README.md、docs/architecture.md、docs/TODO.md、docs/form-exports.md。',
  '建議 55 秒。下一步建議與承辦及估價專業人員選擇同一批合適案件，確認基準後做平行試辦。量測每件總工時，納入 OCR 後人工核對及疑義處理；追蹤漏檢、誤報與待確認項目，才能回答是否真正減輕工作負擔。需要機關提供適用測資、經確認基準與共同驗證人員。呼叫雲端模型前仍須依競賽規範確認資料適用性。這是提案的下一步，目前沒有已完成的效益百分比。謝謝。依據：本簡報依現況提出之試辦建議。',
];

export const transition: SlideTransition = {
  duration: 240,
  exit: { duration: 160, easing: 'ease-in', keyframes: [{ opacity: 1 }, { opacity: 0 }] },
  enter: { duration: 240, delay: 40, easing: 'ease-out', keyframes: [{ opacity: 0 }, { opacity: 1 }] },
};

export const meta: SlideMeta = {
  title: '沒有錯的地方 Landwise｜讓估價審查，有依據、可追溯',
  createdAt: '2026-09-13T01:21:34.302Z',
};

export default [Cover, Problem, Workflow, Responsibilities, Example, Evidence, Product, Validation, Scope, Closing] satisfies Page[];
