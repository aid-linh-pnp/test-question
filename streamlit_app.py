import streamlit as st
import json
import random
from datetime import datetime, timedelta, timezone
import os
import requests
import base64
import re

###############################################################################
# -------------------------------  HELPERS  --------------------------------- #
###############################################################################

def format_question_with_code(text: str, lang: str = "javascript") -> str:
    """Add language label to code‑blocks so Streamlit highlights nicely."""
    code_blocks = re.findall(r"```(.*?)```", text, flags=re.DOTALL)
    for block in code_blocks:
        text = text.replace(
            f"```{block}```",
            f"\n```{lang}\n{block.strip()}\n```",
        )
    return text


def save_to_github(account: str, skill: str, final_result: str, history: list, failed: bool):
    """Push result file to GitHub (needs secrets)."""

    now_utc = datetime.now(timezone.utc)
    hanoi_time = now_utc.astimezone(timezone(timedelta(hours=7)))
    filename = f"{account}_{skill}_{hanoi_time.strftime('%Y%m%d_%H%M%S')}.json"
    file_path = f"results/{filename}"

    file_content = {
        "account": account,
        "skill": skill,
        "final_result": final_result,
        "failed": failed,
        "history": history,
        "timestamp": hanoi_time.isoformat(),
    }

    content_str = json.dumps(file_content, indent=2, ensure_ascii=False)
    content_b64 = base64.b64encode(content_str.encode()).decode()

    url = (
        f"https://api.github.com/repos/{st.secrets.github_username}/"
        f"{st.secrets.github_repo}/contents/{file_path}"
    )

    headers = {
        "Authorization": f"Bearer {st.secrets.github_token}",
        "Accept": "application/vnd.github.v3+json",
    }

    payload = {"message": f"Add {skill} result for {account}", "content": content_b64}
    res = requests.put(url, headers=headers, json=payload)

    if res.status_code in (200, 201):
        st.toast(f"💾 Saved the result for *{skill}* in results/{filename}")
    else:
        st.error(f"❌ Failed to save the summary result. Detail: {res.text}")


def save_result_to_file(account: str, skill: str, result: dict) -> str:
    """Save result JSON to local *results/* folder and return the filepath."""

    os.makedirs("results", exist_ok=True)
    clean_account = account.strip().replace(" ", "_").lower()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{clean_account}_{skill}_{timestamp}.json"
    filepath = os.path.join("results", filename)

    with open(filepath, "w", encoding="utf-8") as f_out:
        json.dump(result, f_out, indent=2, ensure_ascii=False)

    return filepath

###############################################################################
# ------------------------------  ENGINE  ----------------------------------- #
###############################################################################

class AdaptiveTestingEngine:
    """Holds all questions and returns one at random for a given skill/level."""

    def __init__(self, questions_data):
        self.questions_by_key = {}
        for q in questions_data:
            key = f"{q['skill']}_{q['seniority']}_{q['level']}"
            self.questions_by_key.setdefault(key, []).append(q)

    def get_question(self, skill: str, seniority: str, level: int):
        key = f"{skill}_{seniority}_{level}"
        pool = self.questions_by_key.get(key, [])
        return random.choice(pool) if pool else None

    @staticmethod
    def format_level_string(seniority: str, level: int):
        reverse_map = {"fresher": "F", "junior": "J", "middle": "M", "senior": "S"}
        return f"{reverse_map.get(seniority, '?')}{level}"


class AdaptiveTestSession:
    """Tracks state for a *single* skill run (max five questions)."""

    def __init__(self, engine: AdaptiveTestingEngine, skill: str, start_seniority="middle"):
        self.engine = engine
        self.skill = skill
        self.starting_seniority = start_seniority
        self.current_seniority = start_seniority
        self.current_level = 3  # Always start at level 3
        self.answer_history = []
        self.question_history = []
        self.is_finished = False
        self.final_result: str | None = None
        self.failed = False
        self.path_state = "initial"

    # --------------------------------------------------------------------- #
    # Core helpers

    def _finish_test(self, label: str, failed: bool = False):
        self.is_finished = True
        self.final_result = label
        self.failed = failed

    def _get_result(self):
        return {
            "is_finished": self.is_finished,
            "final_result": self.final_result,
            "failed": self.failed,
        }

    # --------------------------------------------------------------------- #
    # Public API used by Streamlit app

    def get_next_question(self):
        if self.is_finished:
            return None
        q = self.engine.get_question(self.skill, self.current_seniority, self.current_level)
        if q is None:
            # No question available → abort gracefully
            self._finish_test("NO_QUESTION_AVAILABLE", failed=True)
            return None

        shuffled_q = q.copy()
        shuffled_options = q["options"].copy()
        random.shuffle(shuffled_options)
        shuffled_q["options"] = shuffled_options
        self.question_history.append(shuffled_q)
        return shuffled_q

    def submit_answer(self, selected_idx: int):
        if self.is_finished or not self.question_history:
            return {"error": "No active question"}

        question = self.question_history[-1]
        correct = question["options"][selected_idx]["isAnswerKey"]

        self.answer_history.append(
            {
                "question_id": question["id"],
                "selected_index": selected_idx,
                "is_correct": correct,
            }
        )

        # Dispatch to the correct branching algorithm
        if self.starting_seniority == "middle":
            return self._update_state_after_answer_middle(correct)
        # Other seniorities are TODO
        self._finish_test("UNSUPPORTED_SENIORITY", failed=True)
        return self._get_result()

    def _update_state_after_answer_middle(self, is_correct):

        if len(self.answer_history) == 1:
            if is_correct:
                self.current_seniority = 'middle'
                self.current_level = 5
                self.path_state = 'M5'
            else:
                self.current_seniority = 'middle'
                self.current_level = 1
                self.path_state = 'M1'

        # Q2 – M5 hoặc M1
        elif len(self.answer_history) == 2:
            if self.path_state == 'M5':
                if is_correct:
                    self.current_seniority = 'senior'
                    self.current_level = 3
                    self.path_state = 'S3'
                else:
                    self.current_seniority = 'middle'
                    self.current_level = 4
                    self.path_state = 'M4'
            elif self.path_state == 'M1':
                if is_correct:
                    self.current_seniority = 'middle'
                    self.current_level = 2
                    self.path_state = 'M2'
                else:
                    self.current_seniority = 'junior'
                    self.current_level = 3
                    self.path_state = 'J3'

        # Q3 – M2 / M4 / S3 / J3
        elif len(self.answer_history) == 3:
            if self.path_state == 'M2':
                if is_correct:
                    self._finish_test("LEVELM2")
                else:
                    self._finish_test("LEVELM1")
                return self._get_result()
            elif self.path_state == 'M4':
                if is_correct:
                    self._finish_test("LEVELM4")
                else:
                    self._finish_test("LEVELM3")
                return self._get_result()
            elif self.path_state == 'S3':
                if is_correct:
                    self.current_seniority = 'senior'
                    self.current_level = 5
                    self.path_state = 'S5'
                else:
                    self.current_seniority = 'senior'
                    self.current_level = 1
                    self.path_state = 'S1'
            elif self.path_state == 'J3':
                if is_correct:
                    self.current_seniority = 'junior'
                    self.current_level = 5
                    self.path_state = 'J5'
                else:
                    self.current_seniority = 'junior'
                    self.current_level = 1
                    self.path_state = 'J1'

        # Q4 – S5 / S1 / J5 / J1
        elif len(self.answer_history) == 4:
            if self.path_state == 'S5':
                if is_correct:
                    self._finish_test("LEVELS5")
                else:
                    self.current_seniority = 'senior'
                    self.current_level = 4
                    self.path_state = 'S4'
            elif self.path_state == 'S1':
                if is_correct:
                    self.current_seniority = 'senior'
                    self.current_level = 2
                    self.path_state = 'S2'
                else:
                    self._finish_test("LEVELM5")
                return self._get_result()
            elif self.path_state == 'J5':
                if is_correct:
                    self._finish_test("LEVELJ5")
                else:
                    self.current_seniority = 'junior'
                    self.current_level = 4
                    self.path_state = 'J4'
            elif self.path_state == 'J1':
                if is_correct:
                    self.current_seniority = 'junior'
                    self.current_level = 2
                    self.path_state = 'J2'
                else:
                    self._finish_test("LEVELJ0", failed=True)
                return self._get_result()

        # Q5 – S4 / S2 / J4 / J2
        elif len(self.answer_history) == 5:
            if self.path_state == 'S4':
                if is_correct:
                    self._finish_test("LEVELS4")
                else:
                    self._finish_test("LEVELS3")
            elif self.path_state == 'S2':
                if is_correct:
                    self._finish_test("LEVELS2")
                else:
                    self._finish_test("LEVELS1")
            elif self.path_state == 'J4':
                if is_correct:
                    self._finish_test("LEVELJ4")
                else:
                    self._finish_test("LEVELJ3")
            elif self.path_state == 'J2':
                if is_correct:
                    self._finish_test("LEVELJ2")
                else:
                    self._finish_test("LEVELJ1")

        return self._get_result()


    def _update_state_after_answer_senior(self, is_correct):
        """
        Cập nhật trạng thái bài test sau mỗi câu trả lời,
        theo cây nhánh: bắt đầu từ S3, rồi xuống S1, rồi M3 nếu cần.
        """
        if len(self.answer_history) == 1:  # Q1: S3
            if is_correct:
                self.current_seniority = 'senior'
                self.current_level = 5
                self.path_state = 'S5'
            else:
                self.current_seniority = 'senior'
                self.current_level = 1
                self.path_state = 'S1'

        elif len(self.answer_history) == 2:
            if self.path_state == 'S5':
                if is_correct:
                    self._finish_test("LEVELS5")
                else:
                    self.current_seniority = 'senior'
                    self.current_level = 4
                    self.path_state = 'S4'
            elif self.path_state == 'S1':
                if is_correct:
                    self.current_seniority = 'senior'
                    self.current_level = 2
                    self.path_state = 'S2'
                else:
                    self.current_seniority = 'middle'
                    self.current_level = 3
                    self.path_state = 'M3'

        elif len(self.answer_history) == 3:
            if self.path_state == 'S4':
                if is_correct:
                    self._finish_test("LEVELS4")
                else:
                    self._finish_test("LEVELS3")
                return self._get_result()
            elif self.path_state == 'S2':
                if is_correct:
                    self._finish_test("LEVELS2")
                else:
                    self._finish_test("LEVELS1")
                return self._get_result()
            elif self.path_state == 'M3':
                if is_correct:
                    self.current_seniority = 'middle'
                    self.current_level = 5
                    self.path_state = 'M5'
                else:
                    self.current_seniority = 'middle'
                    self.current_level = 1
                    self.path_state = 'M1'

        elif len(self.answer_history) == 4:
            if self.path_state == 'M5':
                if is_correct:
                    self._finish_test("LEVELM5")
                else:
                    self.current_seniority = 'middle'
                    self.current_level = 4
                    self.path_state = 'M4'
            elif self.path_state == 'M1':
                if is_correct:
                    self.current_seniority = 'middle'
                    self.current_level = 2
                    self.path_state = 'M2'
                else:
                    self._finish_test("LEVELM0", failed=True)

        elif len(self.answer_history) == 5:
            if self.path_state == 'M4':
                if is_correct:
                    self._finish_test("LEVELM4")
                else:
                    self._finish_test("LEVELM3")
            elif self.path_state == 'M2':
                if is_correct:
                    self._finish_test("LEVELM2")
                else:
                    self._finish_test("LEVELM1")

        return self._get_result()


    def _update_state_after_answer_fresher(self, is_correct):
        if len(self.answer_history) == 1:  # Q1: F3
            if is_correct:
                self.current_seniority = 'fresher'
                self.current_level = 5
                self.path_state = 'F5'
            else:
                self.current_seniority = 'fresher'
                self.current_level = 1
                self.path_state = 'F1'

        elif len(self.answer_history) == 2:
            if self.path_state == 'F5':
                if is_correct:
                    self.current_seniority = 'junior'
                    self.current_level = 3
                    self.path_state = 'J3'
                else:
                    self.current_seniority = 'fresher'
                    self.current_level = 4
                    self.path_state = 'F4'
            elif self.path_state == 'F1':
                if is_correct:
                    self.current_seniority = 'fresher'
                    self.current_level = 2
                    self.path_state = 'F2'
                else:
                    self._finish_test("LEVELF0", failed=True)
                    return self._get_result()

        elif len(self.answer_history) == 3:
            if self.path_state == 'F4':
                if is_correct:
                    self._finish_test("LEVELF4")
                else:
                    self._finish_test("LEVELF3")
                return self._get_result()
            elif self.path_state == 'F2':
                if is_correct:
                    self._finish_test("LEVELF2")
                else:
                    self._finish_test("LEVELF1")
                return self._get_result()
            elif self.path_state == 'J3':
                if is_correct:
                    self.current_seniority = 'junior'
                    self.current_level = 5
                    self.path_state = 'J5'
                else:
                    self.current_seniority = 'junior'
                    self.current_level = 1
                    self.path_state = 'J1'

        elif len(self.answer_history) == 4:
            if self.path_state == 'J5':
                if is_correct:
                    self._finish_test("LEVELJ5")
                else:
                    self.current_seniority = 'junior'
                    self.current_level = 4
                    self.path_state = 'J4'
            elif self.path_state == 'J1':
                if is_correct:
                    self.current_seniority = 'junior'
                    self.current_level = 2
                    self.path_state = 'J2'
                else:
                    self._finish_test("LEVELF5")

        elif len(self.answer_history) == 5:
            if self.path_state == 'J4':
                if is_correct:
                    self._finish_test("LEVELJ4")
                else:
                    self._finish_test("LEVELJ3")
            elif self.path_state == 'J2':
                if is_correct:
                    self._finish_test("LEVELJ2")
                else:
                    self._finish_test("LEVELJ1")

        return self._get_result()



    def _update_state_after_answer_junior(self, is_correct):
        if len(self.answer_history) == 1:
            if is_correct:
                self.current_seniority = 'junior'
                self.current_level = 5
                self.path_state = 'J5'
            else:
                self.current_seniority = 'junior'
                self.current_level = 1
                self.path_state = 'J1'

        elif len(self.answer_history) == 2:
            if self.path_state == 'J5':
                if is_correct:
                    self.current_seniority = 'middle'
                    self.current_level = 3
                    self.path_state = 'M3'
                else:
                    self.current_seniority = 'junior'
                    self.current_level = 4
                    self.path_state = 'J4'
            elif self.path_state == 'J1':
                if is_correct:
                    self.current_seniority = 'junior'
                    self.current_level = 2
                    self.path_state = 'J2'
                else:
                    self.current_seniority = 'fresher'
                    self.current_level = 3
                    self.path_state = 'F3'

        elif len(self.answer_history) == 3:
            if self.path_state == 'J2':
                if is_correct:
                    self._finish_test("LEVELJ2")
                else:
                    self._finish_test("LEVELJ1")
                return self._get_result()
            elif self.path_state == 'J4':
                if is_correct:
                    self._finish_test("LEVELJ4")
                else:
                    self._finish_test("LEVELJ3")
                return self._get_result()
            elif self.path_state == 'M3':
                if is_correct:
                    self.current_seniority = 'middle'
                    self.current_level = 5
                    self.path_state = 'M5'
                else:
                    self.current_seniority = 'middle'
                    self.current_level = 1
                    self.path_state = 'M1'
            elif self.path_state == 'F3':
                if is_correct:
                    self.current_seniority = 'fresher'
                    self.current_level = 5
                    self.path_state = 'F5'
                else:
                    self.current_seniority = 'fresher'
                    self.current_level = 1
                    self.path_state = 'F1'

        elif len(self.answer_history) == 4:
            if self.path_state == 'M5':
                if is_correct:
                    self._finish_test("LEVELM5")
                else:
                    self.current_seniority = 'middle'
                    self.current_level = 4
                    self.path_state = 'M4'
            elif self.path_state == 'M1':
                if is_correct:
                    self.current_seniority = 'middle'
                    self.current_level = 2
                    self.path_state = 'M2'
                else:
                    self._finish_test("LEVELJ5")
                return self._get_result()
            elif self.path_state == 'F5':
                if is_correct:
                    self._finish_test("LEVELF5")
                else:
                    self.current_seniority = 'fresher'
                    self.current_level = 4
                    self.path_state = 'F4'
            elif self.path_state == 'F1':
                if is_correct:
                    self.current_seniority = 'fresher'
                    self.current_level = 2
                    self.path_state = 'F2'
                else:
                    self._finish_test("LEVELF0", failed=True)
                return self._get_result()

        elif len(self.answer_history) == 5:
            if self.path_state == 'M4':
                if is_correct:
                    self._finish_test("LEVELM4")
                else:
                    self._finish_test("LEVELM3")
            elif self.path_state == 'M2':
                if is_correct:
                    self._finish_test("LEVELM2")
                else:
                    self._finish_test("LEVELM1")
            elif self.path_state == 'F4':
                if is_correct:
                    self._finish_test("LEVELF4")
                else:
                    self._finish_test("LEVELF3")
            elif self.path_state == 'F2':
                if is_correct:
                    self._finish_test("LEVELF2")
                else:
                    self._finish_test("LEVELF1")

        return self._get_result()

###############################################################################
# -------------------------  STREAMLIT USER INTERFACE  ---------------------- #
###############################################################################

SKILLS = ["html", "css", "javascript", "react", "github"]

st.set_page_config(page_title="Adaptive Multi‑Skill Quiz", layout="centered")
st.title("Adaptive Question Demo – FWA.AT")
st.markdown("<span style='color:green; font-weight:bold;'>Seniority: fresher, junior, middle, senior</span>", unsafe_allow_html=True)
st.markdown("<span style='color:green; font-weight:bold;'>Mỗi Seniority (fresher, junior, middle, senior) có 5 cấp độ từ 1 đến 5, với cấp độ 1 là thấp nhất và 5 là cao nhất.</span>", unsafe_allow_html=True)
st.markdown("<span style='color:green; font-weight:bold;'>Ví dụ: fresher cấp độ 1 là F1, fresher cấp độ 2 là F2, ...", unsafe_allow_html=True)

# --------------------------------- Load questions ------------------------- #

@st.cache_data
def load_questions():
    with open("merged_file.json", "r", encoding="utf-8") as f_in:
        return json.load(f_in)

questions_data = load_questions()

# --------------------------  SESSION STATE SETUP  --------------------------- #

if "initialized" not in st.session_state:
    st.session_state["initialized"] = True
    st.session_state["testing_started"] = False  # Flag after user clicks Start
    st.session_state["skills_queue"] = []
    st.session_state["current_skill"] = None
    st.session_state["session"] = None
    st.session_state["overall_results"] = {}
    st.session_state["overall_details"] = []
    st.session_state["overall_saved"] = False
    st.session_state["account"] = ""
    st.session_state["engine"] = AdaptiveTestingEngine(questions_data)
    st.session_state["start_seniority"] = "middle"

# -----------------------  STEP 0 – Start full test  ------------------------ #

if not st.session_state["testing_started"]:
    account = st.text_input("👤 Enter your account:")
    seniority_choice = st.radio(
    "Chọn cấp độ bắt đầu:",
    ["fresher", "junior", "middle", "senior"],
    horizontal=True,          # hiển thị ngang hàng
    )    

    if st.button("🚀 Start the assessment"):
        if not account.strip():
            st.warning("❌ Please enter your account.")
        else:
            st.session_state["account"] = account.strip()
            st.session_state["start_seniority"] = seniority_choice
            st.session_state["skills_queue"] = SKILLS.copy()
            st.session_state["testing_started"] = True
            st.rerun()

# -----------------------  Main test loop (auto) --------------------------- #
else:

    # Pop next skill if needed
    if st.session_state["current_skill"] is None and st.session_state["skills_queue"]:
        st.session_state["current_skill"] = st.session_state["skills_queue"].pop(0)

    # If no skills left → show summary & save once
    if st.session_state["current_skill"] is None and not st.session_state["skills_queue"]:
        st.header("📊 Summary of results for all 5 skills")
        st.table(st.session_state["overall_results"])

        if not st.session_state["overall_saved"]:
            account = st.session_state["account"]
            combined_label = " | ".join(
                [f"{k}:{v}" for k, v in st.session_state["overall_results"].items()]
            )
            summary_payload = {
                "account": account,
                "results": st.session_state["overall_details"],
                "summary": st.session_state["overall_results"],
                "timestamp": datetime.now().isoformat(),
            }
            try:
                save_result_to_file(account, "multi_skill", summary_payload)
                save_to_github(account, "multi_skill", combined_label, summary_payload, False)
                st.session_state["overall_saved"] = True
            except Exception as e:
                st.error(f"❌ Không thể lưu kết quả tổng hợp: {e}")

        # Offer restart
        if st.button("🔄 Start over"):
            for k in list(st.session_state.keys()):
                del st.session_state[k]
            st.rerun()

    # Otherwise handle current skill
    else:
        current_skill = st.session_state["current_skill"]
        session: AdaptiveTestSession | None = st.session_state["session"]

        # Create session for this skill if needed
        if session is None:
            st.header(f"🛠️ Current skill: **{current_skill.upper()}**")
            session = AdaptiveTestSession(
                engine=st.session_state["engine"],
                skill=current_skill,
                start_seniority=st.session_state["start_seniority"],
            )
            st.session_state["session"] = session
            st.session_state["question"] = session.get_next_question()

        # Show question UI -------------------------------------------------
        if not session.is_finished:
            question = st.session_state["question"]
            level_str = AdaptiveTestingEngine.format_level_string(
                session.current_seniority, session.current_level
            )
            st.subheader(f"📌 Question level: {level_str} ({current_skill})")
            lang_map = {
                "html": "html",
                "css": "css",
                "javascript": "javascript",
                "react": "javascript",
                "github": "bash",
            }
            lang = lang_map.get(current_skill, "text")
            question_md = format_question_with_code(f"**❓ {question['question']}**", lang)
            st.markdown(question_md, unsafe_allow_html=True)

            for idx, option in enumerate(question["options"]):
                if st.button(option["description"], key=f"{current_skill}_opt_{idx}"):
                    result = session.submit_answer(idx)
                    if result.get("error"):
                        st.error(result["error"])
                    if session.is_finished:
                        st.rerun()
                    else:
                        st.session_state["question"] = session.get_next_question()
                        st.rerun()

        # Session finished – store & move on automatically -----------------
        else:
            st.toast(f"🎉 Completed **{current_skill.upper()}** – result: {session.final_result}")
            # Aggregate results
            st.session_state["overall_results"][current_skill] = session.final_result
            st.session_state["overall_details"].append(
                {
                    "skill": current_skill,
                    "final_result": session.final_result,
                    "failed": session.failed,
                    "answer_history": session.answer_history,
                }
            )
            # Reset per‑skill state
            st.session_state["session"] = None
            st.session_state["question"] = None
            st.session_state["current_skill"] = None
            st.rerun()
