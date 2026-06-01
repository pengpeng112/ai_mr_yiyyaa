import sys; sys.path.insert(0,"/app")
from app.config import load_config
from app.services.config_parser import ConfigParser
from app.emr_vastbase_client import fetch_emr_documents_by_visits
cfg = load_config()
e = ConfigParser.parse_emr_vastbase_config(cfg)
r = fetch_emr_documents_by_visits(e, [("00018069","3")], document_kind="discharge")
print("discharge:", len(r.get(("00018069","3"),[])))
r2 = fetch_emr_documents_by_visits(e, [("00018069","3")], document_kind="progress")
print("progress:", len(r2.get(("00018069","3"),[])))
