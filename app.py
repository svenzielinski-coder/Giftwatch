from __future__ import annotations

import re
import streamlit as st
import pandas as pd

from db import (
    init_db, add_idea, list_ideas, get_idea, update_idea,
    add_price_point, get_price_history, get_latest_price,
    set_alert, get_alert
)
from price_fetcher import fetch_price


# ----------------------------
# App config + init
# ----------------------------
st.set_page_config(page_title="GiftWatch", page_icon="🎁", layout="wide")

@st.cache_resource
def _init_db():
    init_db()

_init_db()

st.title("🎁 GiftWatch – Geschenkideen mit Preisverlauf & Preisalarm")


# ----------------------------
# Helpers
# ----------------------------
_URL_RE = re.compile(r"^https?://", re.IGNORECASE)

def is_valid_url(url: str) -> bool:
    return bool(url and _URL_RE.match(url.strip()))

def fmt_price(value) -> str:
    try:
        v = float(value)
    except Exception:
        return str(value)
    # Schönes Format: 2 Nachkommastellen, Komma als Dezimal optional nicht erzwingen
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

CURRENCIES = ["EUR", "USD", "CHF", "GBP"]


# ----------------------------
# Sidebar: Create new idea (form)
# ----------------------------
with st.sidebar:
    st.header("➕ Neue Geschenkidee")

    with st.form("new_idea_form", clear_on_submit=True):
        title = st.text_input("Titel", placeholder="z.B. Sony Kopfhörer", key="new_title")
        url = st.text_input("Produkt-Link", placeholder="https://...", key="new_url")
        person = st.text_input("Für wen?", placeholder="z.B. Mama", key="new_person")
        occasion = st.text_input("Anlass", placeholder="z.B. Geburtstag", key="new_occasion")
        notes = st.text_area("Notizen", placeholder="Wunschfarbe, Größe, etc.", key="new_notes")
        currency = st.selectbox("Währung", CURRENCIES, index=0, key="new_currency")

        submitted = st.form_submit_button("Speichern", type="primary")

    if submitted:
        t = (title or "").strip()
        u = (url or "").strip()
        if not t:
            st.error("Bitte Titel angeben.")
        elif not is_valid_url(u):
            st.error("Bitte einen gültigen Link angeben (muss mit http:// oder https:// beginnen).")
        else:
            new_id = add_idea(
                t, u,
                (person or "").strip(),
                (occasion or "").strip(),
                (notes or "").strip(),
                currency
            )
            st.success(f"Gespeichert (ID {new_id}).")
            st.rerun()


# ----------------------------
# Load ideas
# ----------------------------
ideas = list_ideas(active_only=False) or []
if not ideas:
    st.info("Noch keine Geschenkideen. Links speichern und später Preise tracken 🙂")
    st.stop()

# Table view (left)
df = pd.DataFrame(ideas)
# robust, falls Felder fehlen
for col in ["id", "title", "person", "occasion", "active", "created_at"]:
    if col not in df.columns:
        df[col] = None

df["active"] = df["active"].map({1: "✅", 0: "⛔"}).fillna("⛔")
df = df[["id", "title", "person", "occasion", "active", "created_at"]]

colA, colB = st.columns([1.25, 1])

with colA:
    st.subheader("📋 Ideen")
    st.dataframe(df, use_container_width=True, hide_index=True)

with colB:
    st.subheader("🔎 Detailansicht")

    ids = [int(i["id"]) for i in ideas if "id" in i]
    if not ids:
        st.error("Keine gültigen IDs gefunden.")
        st.stop()

    # default selection persistent
    default_id = st.session_state.get("selected_id", ids[0])
    if default_id not in ids:
        default_id = ids[0]

    selected_id = st.selectbox(
        "Wähle eine Idee (ID)",
        ids,
        index=ids.index(default_id),
        key="selected_id_selectbox"
    )
    st.session_state["selected_id"] = int(selected_id)

    idea = get_idea(int(selected_id))
    if not idea:
        st.error("Idee nicht gefunden.")
        st.stop()

    title = idea.get("title") or "(ohne Titel)"
    url = idea.get("url") or ""
    person = idea.get("person") or "-"
    occasion = idea.get("occasion") or "-"
    currency = idea.get("currency") or "EUR"
    active_flag = int(idea.get("active") or 0)

    st.markdown(f"### {title}")

    if is_valid_url(url):
        st.link_button("🔗 Produkt öffnen", url)
        st.caption(url)
    else:
        st.warning("Link fehlt oder ist ungültig.")

    st.write(f"**Für:** {person}  |  **Anlass:** {occasion}")

    # latest price
    latest = get_latest_price(int(idea["id"]))
    if latest:
        lp = latest.get("price")
        lc = latest.get("currency") or currency
        src = latest.get("source") or ""
        st.metric("Letzter Preis", f"{fmt_price(lp)} {lc}", help=(f"Quelle: {src}" if src else None))
    else:
        st.warning("Noch kein Preis gespeichert.")

    st.divider()

    # ----------------------------
    # Edit idea (form)
    # ----------------------------
    with st.expander("✏️ Bearbeiten", expanded=False):
        form_key = f"edit_form_{idea['id']}"
        with st.form(form_key):
            e_title = st.text_input("Titel", value=title, key=f"e_title_{idea['id']}")
            e_url = st.text_input("Link", value=url, key=f"e_url_{idea['id']}")
            e_person = st.text_input("Für wen?", value=(idea.get("person") or ""), key=f"e_person_{idea['id']}")
            e_occasion = st.text_input("Anlass", value=(idea.get("occasion") or ""), key=f"e_occasion_{idea['id']}")
            e_notes = st.text_area("Notizen", value=(idea.get("notes") or ""), key=f"e_notes_{idea['id']}")
            e_currency = st.selectbox(
                "Währung", CURRENCIES,
                index=CURRENCIES.index(currency) if currency in CURRENCIES else 0,
                key=f"e_currency_{idea['id']}"
            )
            e_active = st.checkbox("Aktiv", value=(active_flag == 1), key=f"e_active_{idea['id']}")

            save_edit = st.form_submit_button("Änderungen speichern")

        if save_edit:
            t = (e_title or "").strip()
            u = (e_url or "").strip()
            if not t:
                st.error("Titel darf nicht leer sein.")
            elif not is_valid_url(u):
                st.error("Bitte gültigen Link angeben (http/https).")
            else:
                update_idea(
                    int(idea["id"]),
                    t, u,
                    (e_person or "").strip(),
                    (e_occasion or "").strip(),
                    (e_notes or "").strip(),
                    e_currency,
                    1 if e_active else 0
                )
                st.success("Gespeichert.")
                st.rerun()

    # ----------------------------
    # Price actions
    # ----------------------------
    c1, c2 = st.columns(2)

    with c1:
        if st.button("🔄 Preis automatisch holen", key=f"fetch_{idea['id']}"):
            if not is_valid_url(url):
                st.error("Ungültiger oder fehlender Produkt-Link.")
            else:
                try:
                    with st.spinner("Hole Preis..."):
                        price, cur, source = fetch_price(url)
                except Exception as e:
                    st.error(f"Fehler beim Preisabruf: {e}")
                else:
                    if price is None:
                        st.error("Keinen Preis gefunden. Nutze 'Manuell eintragen'.")
                    else:
                        add_price_point(
                            int(idea["id"]),
                            float(price),
                            currency=(cur or currency),
                            source=(source or "auto")
                        )
                        st.success(f"Preis gespeichert: {fmt_price(price)} {(cur or currency)}")
                        st.rerun()

    with c2:
        with st.form(f"manual_price_{idea['id']}"):
            mp = st.text_input("Manueller Preis (z.B. 79.99)", key=f"mp_{idea['id']}")
            mcur = st.selectbox("Währung (manuell)", CURRENCIES, index=0, key=f"mcur_{idea['id']}")
            submitted_mp = st.form_submit_button("➕ Manuell eintragen")

        if submitted_mp:
            try:
                val = float((mp or "").replace(",", ".").strip())
                if val <= 0:
                    raise ValueError("Preis muss > 0 sein.")
            except Exception:
                st.error("Bitte eine gültige Zahl eingeben, z.B. 79.99")
            else:
                add_price_point(int(idea["id"]), val, currency=mcur, source="manual")
                st.success("Manueller Preis gespeichert.")
                st.rerun()

    st.divider()

    # ----------------------------
    # Alert
    # ----------------------------
    st.subheader("⏰ Preisalarm")
    alert = get_alert(int(idea["id"]))

    default_threshold = 0.0
    alert_active = False
    if alert:
        try:
            default_threshold = float(alert.get("threshold") or 0.0)
        except Exception:
            default_threshold = 0.0
        alert_active = int(alert.get("active") or 0) == 1

    a1, a2, a3 = st.columns([1, 1, 1])
    with a1:
        threshold = st.number_input(
            "Alarm wenn Preis ≤",
            value=float(default_threshold),
            min_value=0.0,
            step=1.0,
            key=f"threshold_{idea['id']}"
        )
    with a2:
        active = st.checkbox("Alarm aktiv", value=alert_active, key=f"alert_active_{idea['id']}")
    with a3:
        if st.button("Alarm speichern", key=f"save_alert_{idea['id']}"):
            set_alert(int(idea["id"]), threshold=float(threshold), active=1 if active else 0)
            st.success("Alarm gespeichert.")
            st.rerun()

    st.subheader("📈 Preisverlauf")
    hist = get_price_history(int(idea["id"])) or []
    if not hist:
        st.info("Noch keine Preishistorie.")
    else:
        hdf = pd.DataFrame(hist)
        # robust: Spalten absichern
        if "timestamp" in hdf.columns:
            hdf["timestamp"] = pd.to_datetime(hdf["timestamp"], errors="coerce")
            hdf = hdf.dropna(subset=["timestamp"])
            if "price" in hdf.columns and not hdf.empty:
                st.line_chart(hdf.set_index("timestamp")["price"], height=220)
        st.dataframe(
            hdf.sort_values("timestamp", ascending=False) if "timestamp" in hdf.columns else hdf,
            use_container_width=True,
            hide_index=True
        )
