import streamlit as st
import pandas as pd

from db import (
    init_db, add_idea, list_ideas, get_idea, update_idea,
    add_price_point, get_price_history, get_latest_price,
    set_alert, get_alert
)
from price_fetcher import fetch_price

# ---------- Wichtig: Debug + DB Init (nicht blockierend) ----------
st.set_page_config(page_title="GiftWatch", page_icon="🎁", layout="wide")
st.write("App gestartet ✅")  # wenn du das siehst, startet Streamlit korrekt

@st.cache_resource
def _init():
    init_db()

_init()
# ---------------------------------------------------------------

st.title("🎁 GiftWatch – Geschenkideen mit Preisverlauf & Preisalarm")

with st.sidebar:
    st.header("➕ Neue Geschenkidee")
    title = st.text_input("Titel", placeholder="z.B. Sony Kopfhörer")
    url = st.text_input("Produkt-Link", placeholder="https://...")
    person = st.text_input("Für wen?", placeholder="z.B. Mama")
    occasion = st.text_input("Anlass", placeholder="z.B. Geburtstag")
    notes = st.text_area("Notizen", placeholder="Wunschfarbe, Größe, etc.")
    currency = st.selectbox("Währung", ["EUR", "USD", "CHF", "GBP"], index=0)

    if st.button("Speichern", type="primary"):
        if not title.strip() or not url.strip():
            st.error("Bitte Titel und Link angeben.")
        else:
            new_id = add_idea(title.strip(), url.strip(), person.strip(), occasion.strip(), notes.strip(), currency)
            st.success(f"Gespeichert (ID {new_id}).")

ideas = list_ideas(active_only=False)
if not ideas:
    st.info("Noch keine Geschenkideen. Links speichern und später Preise tracken 🙂")
    st.stop()

df = pd.DataFrame(ideas)
df["active"] = df["active"].map({1: "✅", 0: "⛔"})
df = df[["id", "title", "person", "occasion", "active", "created_at"]]

colA, colB = st.columns([1.2, 1])

with colA:
    st.subheader("📋 Ideen")
    st.dataframe(df, use_container_width=True, hide_index=True)

with colB:
    st.subheader("🔎 Detailansicht")
    ids = [i["id"] for i in ideas]
    selected_id = st.selectbox("Wähle eine Idee (ID)", ids)
    idea = get_idea(int(selected_id))
    if not idea:
        st.error("Idee nicht gefunden.")
        st.stop()

    st.markdown(f"### {idea['title']}")
    st.write(f"**Link:** {idea['url']}")
    st.write(f"**Für:** {idea.get('person','') or '-'}  |  **Anlass:** {idea.get('occasion','') or '-'}")

    latest = get_latest_price(idea["id"])
    if latest:
        st.metric(
            "Letzter Preis",
            f"{latest['price']} {latest.get('currency','EUR')}",
            help=f"Quelle: {latest.get('source','')}"
        )
    else:
        st.warning("Noch kein Preis gespeichert.")

    with st.expander("✏️ Bearbeiten"):
        e_title = st.text_input("Titel", value=idea["title"])
        e_url = st.text_input("Link", value=idea["url"])
        e_person = st.text_input("Für wen?", value=idea.get("person") or "")
        e_occasion = st.text_input("Anlass", value=idea.get("occasion") or "")
        e_notes = st.text_area("Notizen", value=idea.get("notes") or "")
        e_currency = st.selectbox(
            "Währung", ["EUR", "USD", "CHF", "GBP"],
            index=["EUR", "USD", "CHF", "GBP"].index(idea.get("currency", "EUR"))
        )
        e_active = st.checkbox("Aktiv", value=(idea["active"] == 1))

        if st.button("Änderungen speichern"):
            update_idea(idea["id"], e_title, e_url, e_person, e_occasion, e_notes, e_currency, 1 if e_active else 0)
            st.success("Gespeichert. Seite kurz neu laden oder ID wechseln.")

    st.divider()

    c1, c2 = st.columns(2)

    # Optional: Damit Streamlit nicht „hängt“, wenn fetch_price lange dauert:
    # Wir führen fetch_price nur auf Button-Klick aus (machst du schon) + klarer Fehlertext.
    with c1:
        if st.button("🔄 Preis automatisch holen"):
            try:
                with st.spinner("Hole Preis..."):
                    price, cur, source = fetch_price(idea["url"])
            except Exception as e:
                st.error(f"Fehler beim Preisabruf: {e}")
            else:
                if price is None:
                    st.error("Keinen Preis gefunden. Nutze 'Manuell eintragen'.")
                else:
                    add_price_point(
                        idea["id"],
                        price,
                        currency=(cur or idea.get("currency", "EUR")),
                        source=source
                    )
                    st.success(f"Preis gespeichert: {price} {(cur or idea.get('currency','EUR'))} (Quelle: {source})")

    with c2:
        with st.form("manual_price"):
            mp = st.text_input("Manueller Preis (z.B. 79.99)")
            mcur = st.selectbox("Währung (manuell)", ["EUR", "USD", "CHF", "GBP"], index=0)
            submitted = st.form_submit_button("➕ Manuell eintragen")
            if submitted:
                try:
                    val = float(mp.replace(",", "."))
                    add_price_point(idea["id"], val, currency=mcur, source="manual")
                    st.success("Manueller Preis gespeichert.")
                except Exception:
                    st.error("Bitte Zahl eingeben, z.B. 79.99")

    st.subheader("⏰ Preisalarm")
    alert = get_alert(idea["id"])
    default_threshold = float(alert["threshold"]) if alert else 0.0
    alert_active = (alert["active"] == 1) if alert else False

    a1, a2, a3 = st.columns([1, 1, 1])
    with a1:
        threshold = st.number_input("Alarm wenn Preis ≤", value=default_threshold, min_value=0.0, step=1.0)
    with a2:
        active = st.checkbox("Alarm aktiv", value=alert_active)
    with a3:
        if st.button("Alarm speichern"):
            set_alert(idea["id"], threshold=threshold, active=1 if active else 0)
            st.success("Alarm gespeichert.")

    st.subheader("📈 Preisverlauf")
    hist = get_price_history(idea["id"])
    if not hist:
        st.info("Noch keine Preishistorie.")
    else:
        hdf = pd.DataFrame(hist)
        hdf["timestamp"] = pd.to_datetime(hdf["timestamp"])
        st.line_chart(hdf.set_index("timestamp")["price"], height=220)
        st.dataframe(hdf.sort_values("timestamp", ascending=False), use_container_width=True, hide_index=True)
