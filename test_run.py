import streamlit as st
import time

st.title("Lab Timer Test")

# Initialize timer states
for i in [1, 2]:
    if f"running_{i}" not in st.session_state:
        st.session_state[f"running_{i}"] = False
        st.session_state[f"start_{i}"] = 0.0
        st.session_state[f"elapsed_{i}"] = 0.0


@st.fragment(run_every=0.1)
def show_timers():

    cols = st.columns(2)

    for i, col in enumerate(cols, start=1):
        with col:
            st.subheader(f"Timer {i}")

            # Calculate current elapsed time
            elapsed = st.session_state[f"elapsed_{i}"]

            if st.session_state[f"running_{i}"]:
                elapsed += time.monotonic() - st.session_state[f"start_{i}"]

            st.metric("Elapsed Time", f"{elapsed:.1f} sec")

            c1, c2, c3 = st.columns(3)

            if c1.button("▶ Start", key=f"start_button_{i}"):
                if not st.session_state[f"running_{i}"]:
                    st.session_state[f"start_{i}"] = time.monotonic()
                    st.session_state[f"running_{i}"] = True

            if c2.button("⏹ Stop", key=f"stop_button_{i}"):
                if st.session_state[f"running_{i}"]:
                    st.session_state[f"elapsed_{i}"] += (
                        time.monotonic() - st.session_state[f"start_{i}"]
                    )
                    st.session_state[f"running_{i}"] = False

            if c3.button("↺ Reset", key=f"reset_button_{i}"):
                st.session_state[f"running_{i}"] = False
                st.session_state[f"elapsed_{i}"] = 0.0


show_timers()

# python -m streamlit run test_run.py