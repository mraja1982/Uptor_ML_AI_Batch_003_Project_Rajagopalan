"""Central configuration - change behaviour here, not in the code."""
from pathlib import Path
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / 'data'
CSV_DIR = DATA_DIR / 'csv'
MD_DIR = DATA_DIR / 'md'
PDF_DIR = DATA_DIR / 'pdfs'
for _d in (CSV_DIR, MD_DIR, PDF_DIR):
    _d.mkdir(parents=True, exist_ok=True)
SUPPORTED_EXTENSIONS = ('.csv', '.xlsx', '.xls')
MD_EXTENSIONS = ('.md', '.markdown')
PDF_EXTENSIONS = ('.pdf',)
UPLOAD_ROUTES = {ext: CSV_DIR for ext in SUPPORTED_EXTENSIONS}
UPLOAD_ROUTES.update({ext: MD_DIR for ext in MD_EXTENSIONS})
UPLOAD_ROUTES.update({ext: PDF_DIR for ext in PDF_EXTENSIONS})
CHUNK_CHARS = 900
CHUNK_OVERLAP = 120
TOP_K_DOCS = 4
MIN_DOC_SCORE = 0.25
API_HOST = '127.0.0.1'
API_PORT = 8000
API_URL = f'http://localhost:{API_PORT}/chat'
API_PROACTIVE_URL = f'http://localhost:{API_PORT}/api/proactive-analysis'
API_TIMEOUT = 120
EMBED_MODEL = 'sentence-transformers/all-MiniLM-L6-v2'
LLM_MODEL = 'Qwen/Qwen2.5-1.5B-Instruct'
USE_LLM = True
LLM_MAX_NEW_TOKENS = 500
TOP_K_SIMILAR = 5
MAX_TEXT_CHARS = 500
DATE_DAYFIRST = False
DEDUPE_BY_INCIDENT_ID = True
COLUMN_ALIASES = {'incident_id': ['number', 'incident', 'incident id', 'incident number', 'id', 'ticket', 'ticket id'], 'opened_at': ['opened', 'opened at', 'opened date', 'created', 'created on', 'created date', 'open date', 'start date', 'reported date', 'date', 'sys_created_on', 'open time', 'open_time'], 'closed_at': ['closed', 'closed at', 'closed date', 'resolved', 'resolved at', 'resolved date', 'close date', 'end date', 'resolveddate', 'date', 'sys_closed_on', 'close time', 'close_time', 'sys_resolved_on'], 'priority': ['priority', 'incident priority', 'severity'], 'route_case': ['route case', 'route cases', 'routecase', 'assignment group', 'assigned group', 'resolver group', 'support group', 'category', 'route'], 'closure_code': ['closure code', 'close code', 'closure', 'resolution code', 'closed code', 'close_code'], 'server': ['server', 'ci', 'configuration item', 'cmdb ci', 'server name', 'hostname', 'affected ci', 'server / ci', 'cmdb_ci'], 'description': ['short description', 'short_description', 'description', 'summary', 'title', 'details'], 'resolution': ['resolution notes', 'close notes', 'resolution', 'work notes', 'notes', 'close_notes', 'resolution comments', 'resolution_comments'], 'incident type': ['incident_type', 'incident category', 'incident_category'], 'it service': ['primary group', 'it_service'], 'group': ['assignment group', 'assignment_group'], 'ci_name': ['ci_name', 'ci name', 'ciname', 'configuration item', 'cmdb ci', 'cmdb_ci', 'affected ci', 'server / ci', 'application name', 'application_name']}
PRIORITY_ORDER = ['Critical', 'High', 'Medium', 'Low', 'Unknown']
PRIORITY_PATTERNS = [('Critical', 'critical|\\bp1\\b|^1\\b|sev ?1'), ('High', 'high|\\bp2\\b|^2\\b|sev ?2'), ('Medium', 'medium|moderate|\\bp3\\b|^3\\b|sev ?3'), ('Low', 'low|\\bp4\\b|^4\\b|sev ?4')]
PRIORITY_COLORS = {'Critical': '#C0392B', 'High': '#E67E22', 'Medium': '#F2C12E', 'Low': '#2E86AB', 'Unknown': '#9AA5B1'}
RULES = {'trend_increase_pct': 20, 'top_server_share_pct': 15, 'critical_high_share_pct': 30, 'noise_closure_share_pct': 20, 'top_route_share_pct': 25, 'recurring_min_count': 5}
NOISE_CLOSURE_PATTERN = 'no fault|no issue|no action|false|self.?heal|auto.?clos|duplicate|user error|not reproducible|cannot reproduce|no response'
BRAND_BLUE = '#1F4E79'
ACCENT_TEAL = '#17806D'
ACCENT_ORANGE = '#D9822B'
TOP_N = 10
OLLAMA_URL = 'http://127.0.0.1:11434'
#OLLAMA_MODEL = 'llama3.2:latest'
#OLLAMA_MODEL = 'qwen3:0.6b'
OLLAMA_MODEL = 'llama3.2:1b'
OLLAMA_TEMPERATURE = 0.2
OLLAMA_NUM_PREDICT = 50
OLLAMA_TIMEOUT = 30
API_AGENT_INVESTIGATE_URL = (
    f'http://localhost:{API_PORT}/api/agents/investigate'
)

API_AGENT_ROOT_CAUSE_URL = (
    f'http://localhost:{API_PORT}/api/agents/root-cause'
)

API_AGENT_PROACTIVE_URL = (
    f'http://localhost:{API_PORT}/api/agents/proactive'
)

API_AGENT_FEEDBACK_URL = (
    f'http://localhost:{API_PORT}/api/agents/feedback'
)