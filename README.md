# Resume-Generator

Autogenerate a tailored resume and produce a PDF for upload. To use it, create a `.env` file with your own API key.

## Install

```powershell
python -m pip install -r requirements.txt
```

## Run

Default development server with auto-reload:

```powershell
python app.py
```

Production-style server with `waitress`:

```powershell
$env:USE_WAITRESS="1"
python app.py
Remove-Item Env:USE_WAITRESS
```

The app listens on `127.0.0.1:5000` by default. You can override that with `APP_HOST` and `APP_PORT`, or with `PORT`.
