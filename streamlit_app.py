import streamlit as st
import json
import random
from datetime import datetime, timedelta, timezone
import os
import requests
import base64
import re

def format_question_with_code(text: str, lang: str = "javascript") -> str:

    code_blocks = re.findall(r"```(.*?)```", text, flags=re.DOTALL)
    for block in code_blocks:
        text = text.replace(
            f"```{block}```",
            f"\n```{lang}\n{block.strip()}\n```",
        )
    return text

def save_to_github(account: str, skill: str, final_result: str, history: list, failed: bool):

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
        st.success(f"Đã lưu kết quả *{skill}* tại results/{filename}")
    else:
        st.error(f"Không thể lưu kết quả *{skill}* lên GitHub. Chi tiết: {res.text}")


def save_result_to_file(account: str, skill: str, result: dict) -> str:

    os.makedirs("results", exist_ok=True)
    clean_account = account.strip().replace(" ", "_").lower()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{clean_account}_{skill}_{timestamp}.json"
    filepath = os.path.join("results", filename)

    with open(filepath, "w", encoding="utf-8") as f_out:
        json.dump(result, f_out, indent=2, ensure_ascii=False)

    return filepath


class AdaptiveTestingEngine:

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


SKILLS = ["html", "css", "javascript", "react", "github"]

st.set_page_config(page_title="Adaptive Multi‑Skill Quiz", layout="centered")
st.title("Adaptive Question Demo - FWA.AT (Multi‑Skill)")
st.markdown("<span style='color:green; font-weight:bold;'>Seniority: fresher, junior, middle, senior</span>", unsafe_allow_html=True)
st.markdown("<span style='color:green; font-weight:bold;'>Mỗi Seniority có 5 cấp độ từ 1 đến 5, với cấp độ 1 là thấp nhất và 5 là cao nhất.</span>", unsafe_allow_html=True)
st.markdown("<span style='color:green; font-weight:bold;'>Ví dụ: fresher cấp độ 1 là F1, junior cấp độ 2 là J2, ...", unsafe_allow_html=True)


@st.cache_data
def load_questions():
    with open("merged_file.json", "r", encoding="utf-8") as f_in:
        return json.load(f_in)

questions_data = load_questions()


if "initialized" not in st.session_state:
    st.session_state["initialized"] = True
    st.session_state["skills_queue"] = SKILLS.copy()
    st.session_state["current_skill"] = None
    st.session_state["results_per_skill"] = {}
    st.session_state["session"] = None
    st.session_state["question"] = None
    st.session_state["account"] = ""
    st.session_state["engine"] = AdaptiveTestingEngine(questions_data)
    # st.session_state["result_saved"] = False
    st.session_state["result_saved"] = False      # còn dùng cho từng skill
    st.session_state["seniority"] = None          # <-- thêm
    st.session_state["all_skills_saved"] = False

if st.session_state["current_skill"] is None and st.session_state["skills_queue"]:
    st.session_state["current_skill"] = st.session_state["skills_queue"].pop(0)

current_skill = st.session_state["current_skill"]


if st.session_state["session"] is None:
    st.header(f"Kỹ năng hiện tại: **{current_skill.upper()}**")

    # ----- CASE 1: LẦN ĐẦU TIÊN (chưa có seniority) -----
    if st.session_state.get("seniority") is None:
        # 1.1 Nhập account (chỉ lần đầu)
        account = st.text_input(
            "Nhập account của bạn:",
            value=st.session_state.get("account", ""),
            key="account_input",
        )

        # 1.2 Chọn seniority (chỉ lần đầu)
        seniority = st.selectbox(
            "Chọn cấp độ bắt đầu:",
            ["fresher", "junior", "middle", "senior"],
            key="seniority_select",
        )

        # 1.3 Nút Bắt đầu – vẫn cần cho lần đầu
        if st.button("Bắt đầu kiểm tra", key="start_btn"):
            if not account.strip():
                st.warning("Vui lòng nhập account của bạn.")
            else:
                # Ghi cố định account & seniority
                st.session_state["account"] = account.strip()
                st.session_state["seniority"] = seniority

                # Tạo phiên kiểm tra cho skill đầu tiên
                session = AdaptiveTestSession(
                    engine=st.session_state["engine"],
                    skill=current_skill,
                    start_seniority=seniority,
                )
                st.session_state["session"] = session
                st.session_state["question"] = session.get_next_question()
                st.rerun()

    # ----- CASE 2: ĐÃ CÓ seniority & account (các skill tiếp theo) -----
    else:
        # Tự động tạo session, KHÔNG hiển thị input/nút
        session = AdaptiveTestSession(
            engine=st.session_state["engine"],
            skill=current_skill,
            start_seniority=st.session_state["seniority"],
        )
        st.session_state["session"] = session
        st.session_state["question"] = session.get_next_question()
        st.rerun()


elif not st.session_state["session"].is_finished:
    session: AdaptiveTestSession = st.session_state["session"]
    question = st.session_state["question"]

    level_str = AdaptiveTestingEngine.format_level_string(
        session.current_seniority, session.current_level
    )

    st.subheader(f"Câu hỏi mức độ: {level_str} ({current_skill})")
    lang_map = {
        "html": "html",
        "css": "css",
        "javascript": "javascript",
        "react": "javascript",
        "github": "bash",          # ví dụ
    }
    lang = lang_map.get(current_skill, "text")

    question_md = format_question_with_code(f"❓ {question['question']}**", lang)
    st.markdown(question_md, unsafe_allow_html=True)

    for idx, option in enumerate(question["options"]):
        if st.button(option["description"], key=f"opt_{idx}"):
            result = session.submit_answer(idx)
            if result.get("answer_history"):
                if result["answer_history"]["is_correct"]:
                    st.success("✅ ĐÚNG")
                else:
                    st.error("❌ SAI")

            if not result["is_finished"]:
                st.session_state["question"] = session.get_next_question()
                st.rerun()
            else:
                st.rerun()


else:
    session: AdaptiveTestSession = st.session_state["session"]
    result_label = session.final_result
    failed_flag = session.failed

    st.success("Hoàn thành bài kiểm tra cho kỹ năng này!")
    st.write(f"Kết quả **{current_skill.upper()}**: **{result_label}**")

    if not st.session_state["result_saved"]:
        account = st.session_state["account"]
        final_result_dict = {
            "account": account,
            "skill": current_skill,
            "final_result": result_label,
            "failed": failed_flag,
            "answer_history": session.answer_history,
            "datetime": datetime.now().isoformat(),
        }

        # try:
        #     local_path = save_result_to_file(account, current_skill, final_result_dict)
        #     # st.info(f"💾 Đã lưu file cục bộ: {local_path}")
        # except Exception as e:
        #     st.error(f"❌ Lưu file cục bộ thất bại: {e}")

        # try:
        #     save_to_github(account, current_skill, result_label, session.answer_history, failed_flag)
        # except Exception as e:
        #     st.error(f"❌ Lưu GitHub thất bại: {e}")

        st.session_state["results_per_skill"][current_skill] = {
            "final_result": result_label,
            "failed": failed_flag,
            "answer_history": session.answer_history.copy(),
            "question_history": session.question_history.copy(),   # <-- thêm
        }
        st.session_state["result_saved"] = True

    if st.session_state["skills_queue"]:
        st.session_state["session"] = None
        st.session_state["question"] = None
        st.session_state["result_saved"] = False
        st.session_state["current_skill"] = None  # Trigger pop in next cycle
        st.rerun()
    else:
        st.header("Tổng hợp kết quả tất cả kỹ năng")
        st.table(st.session_state["results_per_skill"])
            # --- Lưu tổng hợp chỉ 1 lần ---
        if not st.session_state["all_skills_saved"]:
            account = st.session_state["account"]
            summary = {
                "account": account,
                "seniority": st.session_state["seniority"],
                "results": st.session_state["results_per_skill"],
                "timestamp": datetime.now().isoformat(),
            }

            try:
                save_result_to_file(account, "allskills", summary)
                save_to_github(account, "allskills", "COMPLETED", summary, False)
                st.success("💾 Đã lưu kết quả tổng hợp cho 5 kỹ năng!")
            except Exception as e:
                st.error(f"Lưu tổng hợp thất bại: {e}")

            st.session_state["all_skills_saved"] = True


        if st.button("🔄 Làm lại từ đầu", key="restart_all"):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()
