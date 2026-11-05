from tollgate_api.service import create_app
from tollgate_api.settings import Settings

app = create_app(Settings.from_env())
