## Frappe PI Validator

Extract tire Proforma Invoices (PDF / Excel) into Frappe.

The extraction engine of `document-intelligence` runs inside the app.
Open the **PI Validator** page (`/app/pi-validator`), upload a PI, and
the product rows (item/code, brand, size, pattern, load/speed, PR,
sidewall, quantity, unit, unit price, amount, currency, qty per 40HQ)
are shown with totals, and can be downloaded as CSV. Tables without
recognizable product columns are shown as found.

Supported: native-text PDF, XLSX, XLSM, XLS. Scanned PDFs and images
need the optional OCR dependencies (see below).

### Installation

Copy (or symlink) this folder into your bench and install it:

```bash
cd ~/frappe-bench
cp -r /path/to/document-intelligence/frappe_pi_validator apps/
./env/bin/pip install -e apps/frappe_pi_validator
grep -qx frappe_pi_validator sites/apps.txt || echo frappe_pi_validator >> sites/apps.txt
bench --site <your-site> install-app frappe_pi_validator
bench restart
```

(If the folder is in a git repository, `bench get-app <repo-url>` does
the copy, pip install and apps.txt steps for you.)

Optional OCR for scanned PDFs / images: install PaddlePaddle for your
machine first, then

```bash
./env/bin/pip install -e "apps/frappe_pi_validator[ocr]"
```

### Usage

- Desk: **PI Validator** page (`/app/pi-validator`) → **Upload PI**.
  Access: System Manager (change the roles on the Page to open it to
  others).
- API: `frappe_pi_validator.api.extract_file(file_url)` returns the
  items, summary and unrecognized tables of an uploaded File
  (`include_result=1` adds the full engine output).

### Updating the engine

The engine lives in `document-intelligence/app` (the FastAPI project).
`frappe_pi_validator/extraction/` is a copy; after changing the engine
there, sync it:

```bash
python sync_engine.py
```

#### License

MIT
