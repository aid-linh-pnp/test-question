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

def save_summary_local(account: str, data: dict) -> str:
    """
    Ghi 1 file JSON duy nhất (tên account + thời gian + _summary.json)
    vào thư mục results/ và trả về đường dẫn.
    """
    os.makedirs("results", exist_ok=True)
    fname = f"{account}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_summary.json"
    path = os.path.join("results", fname)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return path

# ---------------------------------------------------------------------------
# HELPER: đẩy file tổng hợp lên GitHub
# ---------------------------------------------------------------------------
def save_summary_to_github(account: str, data: dict):
    """
    Push cùng 1 file JSON lên repo GitHub (cần st.secrets.* đã cấu hình).
    Chỉ gọi một lần sau khi hoàn tất 5 skill.
    """
    # Tạo tên file kèm múi giờ Hà Nội (UTC+7)
    now_hn = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=7)))
    fname = f"{account}_{now_hn.strftime('%Y%m%d_%H%M%S')}_summary.json"
    path = f"results/{fname}"

    # Mã hoá base64
    content_str = json.dumps(data, indent=2, ensure_ascii=False)
    b64 = base64.b64encode(content_str.encode("utf-8")).decode("ascii")

    url = (
        f"https://api.github.com/repos/"
        f"{st.secrets.github_username}/{st.secrets.github_repo}/contents/{path}"
    )
    headers = {
        "Authorization": f"Bearer {st.secrets.github_token}",
        "Accept": "application/vnd.github.v3+json",
    }
    payload = {
        "message": f"Add summary for {account}",
        "content": b64,
    }

    res = requests.put(url, headers=headers, json=payload)
    if res.status_code in (200, 201):
        st.success(f"💾 Đã lưu tổng hợp lên GitHub: results/{fname}")
    else:
        st.error(f"❌ Không thể lưu lên GitHub. Chi tiết: {res.text}")

def format_question_with_code(text: str, lang: str = "javascript") -> str:
    """
    Tìm các đoạn nằm giữa cặp ``` … ``` rồi gắn nhãn ngôn ngữ cho code-block  
    để Streamlit highlight đẹp mắt.
    """
    # lấy nguyên phần giữa ``` … ```
    code_blocks = re.findall(r"```(.*?)```", text, flags=re.DOTALL)
    for block in code_blocks:
        text = text.replace(
            f"```{block}```",
            f"\n```{lang}\n{block.strip()}\n```",
        )
    return text

def save_to_github(account: str, skill: str, final_result: str, history: list, failed: bool):
    """Push one result file to GitHub (requires secrets to be set)."""

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
        "timestamp": datetime.now().isoformat(),
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
        st.success(f"💾 Đã lưu kết quả *{skill}* tại results/{filename}")
    else:
        st.error(f"❌ Không thể lưu kết quả *{skill}* lên GitHub. Chi tiết: {res.text}")


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
            "answer_history": self.answer_history[-1] if self.answer_history else {},
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
        if self.starting_seniority == "fresher":
            return self._update_state_after_answer_fresher(correct)
        if self.starting_seniority == "junior":
            return self._update_state_after_answer_junior(correct)
        if self.starting_seniority == "middle":
            return self._update_state_after_answer_middle(correct)
        if self.starting_seniority == "senior":
            return self._update_state_after_answer_senior(correct)
        return {"error": "Invalid seniority"}

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

if "app_state" not in st.session_state:          # < thêm từ đây
    st.session_state.app_state = "choose_meta"   # choose_meta → ask_question → summary
    st.session_state.skill_idx = 0               # vị trí trong SKILLS
    st.session_state.sessions = {}               # {skill: AdaptiveTestSession}
    st.session_state.seniority = "middle"        # sẽ ghi đè khi user chọn
    st.session_state.account = ""
    st.session_state.current_question = None

st.set_page_config(page_title="Adaptive Multi‑Skill Quiz", layout="centered")
st.title("Adaptive Question Demo - FWA.AT (Multi‑Skill)")
st.markdown("<span style='color:green; font-weight:bold;'>Seniority: fresher, junior, middle, senior</span>", unsafe_allow_html=True)
st.markdown("<span style='color:green; font-weight:bold;'>Mỗi Seniority có 5 cấp độ từ 1 đến 5, với cấp độ 1 là thấp nhất và 5 là cao nhất.</span>", unsafe_allow_html=True)
st.markdown("<span style='color:green; font-weight:bold;'>Ví dụ: fresher cấp độ 1 là F1, junior cấp độ 2 là J2, ...", unsafe_allow_html=True)

# Load questions exactly once -------------------------------------------------

@st.cache_data
def load_questions():
    with open("merged_file.json", "r", encoding="utf-8") as f_in:
        return json.load(f_in)

questions_data = load_questions()
engine = AdaptiveTestingEngine(questions_data)
if "engine" not in st.session_state:
    st.session_state.engine = engine

# --------------------------  SESSION STATE SETUP  --------------------------- #

# if "initialized" not in st.session_state:
#     st.session_state["initialized"] = True
#     st.session_state["skills_queue"] = SKILLS.copy()
#     st.session_state["current_skill"] = None
#     st.session_state["results_per_skill"] = {}
#     st.session_state["session"] = None
#     st.session_state["question"] = None
#     st.session_state["account"] = ""
#     st.session_state["engine"] = AdaptiveTestingEngine(questions_data)
#     st.session_state["result_saved"] = False

# # Move to next skill if needed -----------------------------------------------
# if st.session_state["current_skill"] is None and st.session_state["skills_queue"]:
#     st.session_state["current_skill"] = st.session_state["skills_queue"].pop(0)

# current_skill = st.session_state["current_skill"]

# --------------------------------------------------------------------------- #
#  STEP 1 – Start a session for the current skill
# --------------------------------------------------------------------------- #

# if st.session_state["session"] is None:
#     st.header(f"🛠️ Kỹ năng hiện tại: **{current_skill.upper()}**")

#     # Account (ask only once, keep across skills)
#     account = st.text_input(
#         "👤 Nhập account của bạn:",
#         value=st.session_state["account"],
#         key="account_input",
#     )
if st.session_state.app_state == "choose_meta":
    account = st.text_input("👤 Nhập account:", value=st.session_state.account)

    # Choose starting seniority for *this* skill
    # seniority = st.selectbox(
    #     "Chọn cấp độ bắt đầu:",
    #     ["fresher", "junior", "middle", "senior"],
    #     key="seniority_select",
    # )
    seniority = st.selectbox(
        "Chọn *một* seniority cho TẤT CẢ kỹ năng:",
        ["fresher", "junior", "middle", "senior"],
        index=["fresher","junior","middle","senior"].index(st.session_state.seniority),
    )

    # if st.button("🚀 Bắt đầu kiểm tra", key="start_btn"):
    #     if not account.strip():
    #         st.warning("❌ Vui lòng nhập account của bạn.")
    #     else:
    #         st.session_state["account"] = account.strip()
    #         session = AdaptiveTestSession(
    #             engine=st.session_state["engine"],
    #             skill=current_skill,
    #             start_seniority=seniority,
    #         )
    #         st.session_state["session"] = session
    #         st.session_state["question"] = session.get_next_question()
    #         st.rerun()
    if st.button("🚀 Bắt đầu 5 kỹ năng"):
        if not account.strip():
            st.warning("❌ Vui lòng nhập account.")
        else:
            st.session_state.account = account.strip()
            st.session_state.seniority = seniority
            first_skill = SKILLS[0]
            st.session_state.sessions[first_skill] = AdaptiveTestSession(
                st.session_state.engine, first_skill, seniority
            )
            st.session_state.app_state = "ask_question"
            st.rerun()

# --------------------------------------------------------------------------- #
#  STEP 2 – Display question & accept answer
# --------------------------------------------------------------------------- #

# ========== FLOW ask_question ==========
elif st.session_state.app_state == "ask_question":
    skill = SKILLS[st.session_state.skill_idx]
    session = st.session_state.sessions[skill]

    # Nếu skill này xong thì chuyển skill kế / hoặc sang summary
    if session.finished:
        st.session_state.skill_idx += 1
        if st.session_state.skill_idx < len(SKILLS):
            next_skill = SKILLS[st.session_state.skill_idx]
            st.session_state.sessions[next_skill] = AdaptiveTestSession(
                st.session_state.engine, next_skill, st.session_state.seniority
            )
            st.rerun()
        else:
            st.session_state.app_state = "summary"
            st.rerun()

    # Nếu chưa xong thì hiển thị câu hỏi
    else:
        if st.session_state.current_question is None:
            st.session_state.current_question = session.next_question()

        q = st.session_state.current_question
        level_code = AdaptiveTestingEngine.level_code(session.seniority, session.level)
        st.subheader(f"🛠️ {skill.upper()} – Cấp độ {level_code}")

        lang_map = {"html":"html","css":"css","javascript":"javascript","react":"javascript","github":"bash"}
        st.markdown(format_question_with_code(f"**❓ {q['question']}**",
                   lang_map.get(skill,"text")), unsafe_allow_html=True)

        for i,opt in enumerate(q["options"]):
            if st.button(opt["description"], key=f"{skill}_{i}"):
                result = session.submit(i)
                st.success("✅ ĐÚNG") if result["answer_history"]["is_correct"] else st.error("❌ SAI")
                st.session_state.current_question = None
                st.rerun()

# --------------------------------------------------------------------------- #
#  STEP 3 – Session finished (save + move on / summary)
# --------------------------------------------------------------------------- #
# ========== MÀN HÌNH summary ==========
elif st.session_state.app_state == "summary":
    st.header("📊 Kết quả 5 kỹ năng")
    summary = {s: {"final_result": sess.final_result,
                   "failed": sess.failed,
                   "answers": sess.answer_history}
               for s, sess in st.session_state.sessions.items()}
    st.table({k: v["final_result"] for k, v in summary.items()})

    if st.button("💾 Lưu KQ 1 lần"):
        data = {"account": st.session_state.account,
                "seniority": st.session_state.seniority,
                "results": summary,
                "timestamp": datetime.now().isoformat()}
        local_path = save_summary_local(st.session_state.account, data)
        st.success(f"Đã lưu cục bộ: {local_path}")
        save_summary_to_github(st.session_state.account, data)

    if st.button("🔄 Làm lại"):
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.rerun()



# else:
#     session: AdaptiveTestSession = st.session_state["session"]
#     result_label = session.final_result
#     failed_flag = session.failed

#     st.success("🎉 Hoàn thành bài kiểm tra cho kỹ năng này!")
#     st.write(f"🏁 Kết quả **{current_skill.upper()}**: **{result_label}**")

#     # Save only once per skill ---------------------------------------------
#     if not st.session_state["result_saved"]:
#         account = st.session_state["account"]
#         final_result_dict = {
#             "account": account,
#             "skill": current_skill,
#             "final_result": result_label,
#             "failed": failed_flag,
#             "answer_history": session.answer_history,
#             "datetime": datetime.now().isoformat(),
#         }

#         try:
#             local_path = save_result_to_file(account, current_skill, final_result_dict)
#             # st.info(f"💾 Đã lưu file cục bộ: {local_path}")
#         except Exception as e:
#             st.error(f"❌ Lưu file cục bộ thất bại: {e}")

#         try:
#             save_to_github(account, current_skill, result_label, session.answer_history, failed_flag)
#         except Exception as e:
#             st.error(f"❌ Lưu GitHub thất bại: {e}")

#         st.session_state["results_per_skill"][current_skill] = result_label
#         st.session_state["result_saved"] = True

#     # Continue or finish ----------------------------------------------------
#     if st.session_state["skills_queue"]:
#         if st.button("➡️ Tiếp tục kỹ năng kế tiếp", key="next_skill_btn"):
#             # Reset per‑skill state, keep account & summary
#             st.session_state["session"] = None
#             st.session_state["question"] = None
#             st.session_state["result_saved"] = False
#             st.session_state["current_skill"] = None  # Trigger pop in next cycle
#             st.rerun()
#     else:
#         st.header("📊 Tổng hợp kết quả tất cả kỹ năng")
#         st.table(st.session_state["results_per_skill"])

#         # Optionally allow restart ------------------------------------------------
#         if st.button("🔄 Làm lại từ đầu", key="restart_all"):
#             for key in list(st.session_state.keys()):
#                 del st.session_state[key]
#             st.rerun()

# final
