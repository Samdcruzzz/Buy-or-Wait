"""
Rule-based classifier for messages.csv.

The dataset generator uses a small, fixed set of semantic templates, each rendered with
different company names / greetings and in English or Indonesian. Every template is
identifiable by a distinctive phrase that survives translation (proper nouns like
"arrears"/"tunggakan" are consistent), so we classify each message by keyword match,
then pull out amount/date/percent with regex. This gives deterministic, auditable
"structured facts" out of unstructured text without needing a live LLM call.

Every action below is intentionally conservative: if a template only confirms
information that the deterministic engine already derives from financial_events.csv
(a settled/scheduled row, an 'unrealized' investment, a 'pending' status, etc.), we
mark it NOOP rather than re-encode it, to avoid double effects. Only templates that
introduce a *new* fact not otherwise present in financial_events.csv result in an
override action.
"""
import re
from dataclasses import dataclass, field
from typing import Optional

AMOUNT_RE = re.compile(r'([A-Z]{3})\s*([0-9]+(?:[.,][0-9]+)*)')
DATE_RE = re.compile(r'(\d{4}-\d{2}-\d{2})')
PCT_RE = re.compile(r'(\d+(?:\.\d+)?)\s*%')


def extract_amount(text):
    m = AMOUNT_RE.search(text)
    if not m:
        return None, None
    cur = m.group(1)
    raw = m.group(2).replace(',', '')
    try:
        return cur, float(raw)
    except ValueError:
        return cur, None


def extract_all_amounts(text):
    return [(m.group(1), float(m.group(2).replace(',', ''))) for m in AMOUNT_RE.finditer(text)]


def extract_date(text):
    m = DATE_RE.search(text)
    return m.group(1) if m else None


def extract_all_dates(text):
    return DATE_RE.findall(text)


def extract_pct(text):
    m = PCT_RE.search(text)
    return float(m.group(1)) if m else None


# Each rule: (action_name, [keyword-fragments that must ALL be present in EITHER the EN or ID phrasing])
# We check case-insensitively against the raw text for any of the given fragment alternatives.
RULES = [
    # --- NOOP / informational (already reflected in financial_events.csv by status) ---
    ("NOOP_DISPUTE", ["still being investigated", "masih dalam penyelidikan"]),
    ("NOOP_RETRY_DEBIT", ["another debit will be attempted", "debit lain akan dicoba", "another debit may be attempted"]),
    ("NOOP_SELF_TRANSFER", ["transfer between your two accounts", "transfer antara dua rekening"]),
    ("NOOP_TWO_CARDS", ["two separate card accounts", "dua rekening kartu"]),
    ("NOOP_BONUS_PENDING", ["still subject to the final performance review", "menunggu hasil akhir penilaian kinerja"]),

    ("NOOP_REIMBURSEMENT", ["reimbursement for your earlier work expense", "penggantian atas biaya kerja"]),
    ("NOOP_FX_SETTLEMENT_INFO", ["will convert it using the rate applied on the settlement date", "akan mengonversinya dengan kurs pada tanggal penyelesaian"]),
    ("NOOP_UNREALIZED_VALUE", ["no units have been sold and no cash proceeds", "belum dijual dan tidak ada transaksi tunai"]),
    ("NOOP_SALE_SETTLED_INFO", ["sale order is complete and there are no remaining proceeds", "perintah penjualan sudah selesai"]),
    ("NOOP_PRIZE_SETTLED_INFO", ["prize proceeds have reached your account after withholding", "hadiah proceeds", "hadiah uang tunai telah masuk"]),
    ("NOOP_PRIZE_PENDING", ["still in payment processing", "masih dalam proses pembayaran"]),
    ("NOOP_REFUND_PENDING", ["refund has been initiated but has not reached", "pengembalian dana sudah diproses, tetapi belum masuk"]),
    ("NOOP_FX_REFUND_PENDING", ["foreign-currency refund is still processing", "tagihan dikenakan dalam mata uang asing", "pengembalian dana dalam mata uang asing"]),
    ("NOOP_MERCHANT_CONFIRMED", ["was paid in", "receipt has the final amount"]),
    ("GIG_INCOME_UNCERTAIN", ["payout is still pending", "pembayaran berikutnya dari", "masih tertunda"]),
    ("NOOP_MAINTENANCE_CONFIRMED", ["property maintenance payment was received", "pembayaran perawatan properti"]),
    ("NOOP_CONVERSION_CROSSREF", ["employer has confirmed a", "salary credit for"]),
    ("NOOP_UNREALIZED_VALUE2", ["displayed market value has increased", "displayed market value has fallen", "displayed value of the investment has fallen", "nilai investasi yang ditampilkan telah"]),
    ("NOOP_FX_BILL_INFO", ["bill was charged in a foreign currency", "tagihan dikenakan dalam mata uang asing"]),
    ("NOOP_ROUTINE_CONFIRMED", ["regular salary for the next payroll is already confirmed", "gaji rutin untuk penggajian berikutnya sudah dikonfirmasi"]),

    # --- Actionable overrides ---
    ("SCAM_ADVANCE_FEE", ["pay the release charge", "pay the processing charge", "bayar biaya pencairan", "bayar biaya pemrosesan"]),

    ("EMPLOYMENT_ENDED", ["employment has ended", "hubungan kerja anda telah berakhir", "no regular salary payments scheduled after the final settlement", "tidak ada pembayaran gaji rutin yang dijadwalkan setelah penyelesaian akhir"]),
    ("SEASONAL_ENDED", ["seasonal contract has ended", "kontrak musiman saat ini telah berakhir"]),
    ("ONE_SOURCE_ENDED_REMAINING", ["household employment record has ended", "sumber pendapatan kerja rumah tangga telah berakhir", "one household employment"]),

    ("ARREARS_ONE_TIME", ["one-time arrears adjustment", "penyesuaian tunggakan satu kali"]),
    ("RESUME_WITH_NEW_EXPENSE", ["resumes on", "childcare payment begins", "kembali mulai", "pengasuhan anak"]),

    ("LEAVE_REDUCED_NEXT", ["next salary is reduced to", "gaji anda berikutnya dikurangi menjadi", "next salary is reduced", "gaji berikutnya dikurangi"]),
    ("TEMP_REDUCED_NEXT", ["temporary monthly pay is", "gaji bulanan sementara anda adalah"]),

    ("PERMANENT_INCREASE", ["monthly salary has increased to", "gaji bulanan anda naik menjadi"]),

    ("DATE_CHANGE", ["confirmed salary is now expected on", "gaji yang sudah dikonfirmasi kini diperkirakan masuk pada"]),

    ("NEW_JOB_FIRST_SALARY", ["first salary from the new employer", "first salary will be", "first salary of", "gaji pertama anda sebesar", "gaji pertama dari perusahaan baru", "gaji pertama akan"]),

    ("BASE_SALARY_CONFIRMED", ["confirmed base salary is", "gaji pokok yang dikonfirmasi adalah"]),

    ("INVOICE_CONFIRMED_ONE_TIME", ["client approved an invoice payment", "klien menyetujui pembayaran faktur"]),

    ("RENT_INCREASE_PCT", ["renewed lease increases monthly rent", "perpanjangan sewa menaikkan biaya sewa bulanan"]),
]


def classify(text: str):
    """Return (action_name, text) for the first matching rule, or (None, text)."""
    low = text.lower()
    for action, fragments in RULES:
        for frag in fragments:
            if frag.lower() in low:
                return action, text
    return None, text
