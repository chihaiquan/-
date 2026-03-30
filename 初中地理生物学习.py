import streamlit as st
import requests
import json
import time
import math
import random
import os
import base64

# ================= 1. 配置与常量 =================
API_URL = "https://api.siliconflow.cn/v1/chat/completions"

# 已将默认模型修改为您指定的 Qwen3 视觉模型
MODEL_NAME = "Qwen/Qwen3-VL-8B-Instruct" 

DIFFICULTY_SETTINGS = {
    "普通": {"coeff": 1.0, "desc": "基础概念，看图直白提问"},
    "高级": {"coeff": 1.5, "desc": "结合图片细节综合运用"},
    "专家": {"coeff": 2.0, "desc": "看图推导深层原理"},
    "地狱": {"coeff": 3.0, "desc": "中考压轴级读图题"},
    "超神": {"coeff": 5.0, "desc": "竞赛级复杂图表分析"}
}

# ================= 2. 本地图库配置区 =================
# 只需要告诉程序图片在哪，是什么学科。AI 会自己看图识别内容。
IMAGE_LIBRARY = [
    # 生物图库 (请确保您的 images 文件夹下有这些图片，或者修改为真实的文件名)
    {"path": "images/cell.webp", "subject": "生物"},
    {"path": "images/heart.png", "subject": "生物"},
    # 地理图库
    {"path": "images/contour.webp", "subject": "地理"},
    {"path": "images/china_map.png", "subject": "地理"}
]

# ================= 3. 状态初始化 =================
if 'page' not in st.session_state:
    st.session_state.page = 'home'
if 'total_points' not in st.session_state:
    st.session_state.total_points = 0.0
if 'exam_data' not in st.session_state:
    st.session_state.exam_data = None
if 'user_answers' not in st.session_state:
    st.session_state.user_answers = {}

# ================= 4. 核心逻辑：视觉 API 交互 =================
def clean_json_response(text):
    text = text.strip()
    if text.startswith("```json"): text = text[7:]
    elif text.startswith("```"): text = text[3:]
    if text.endswith("```"): text = text[:-3]
    return text.strip()

def encode_image_to_base64(image_path):
    """将本地图片转换为 Base64 编码，以便发给 AI 的'眼睛'"""
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

def get_image_mime_type(image_path):
    """根据后缀名获取图片类型"""
    ext = image_path.split('.')[-1].lower()
    if ext in ['jpg', 'jpeg']: return 'image/jpeg'
    elif ext == 'png': return 'image/png'
    elif ext == 'webp': return 'image/webp'
    return 'image/jpeg'

def generate_questions_chunk(api_key, subject, difficulty, mcq_count, essay_count, image_info=None):
    """调用视觉大模型生成题目"""
    
    # 基础文字 Prompt
    text_prompt = f"""
    你是一个资深的初中{subject}高级教师。请生成一小批难度为【{difficulty}】的测试题。
    你需要生成：{mcq_count} 道普通单项选择题 (type: choice)，{essay_count} 道论述题 (type: essay)。
    """
    
    # 构建发给 AI 的消息内容（多模态格式）
    message_content = []
    
    if image_info and os.path.exists(image_info['path']):
        # 如果有图片，加入图片指令和图片数据
        text_prompt += f"""
        此外，我还为你提供了一张真实的教学图片。
        请你仔细观察这张图片的内容（注意图上的结构、字母、数字或文字标注），
        根据你在这张图上看到的具体信息，自主出一道【识图单选题】(type: image_recognition)。
        """
        base64_image = encode_image_to_base64(image_info['path'])
        mime_type = get_image_mime_type(image_info['path'])
        
        # 将图片加入消息
        message_content.append({
            "type": "image_url",
            "image_url": {"url": f"data:{mime_type};base64,{base64_image}"}
        })
    
    text_prompt += """
    请严格以 JSON 格式输出，必须包含 "questions" 数组。JSON结构示例：
    {
      "questions": [
        {
          "id": 1,
          "type": "choice",
          "question": "题干",
          "options": {"A": "选项1", "B": "选项2", "C": "选项3", "D": "选项4"},
          "answer": "A",
          "explanation": "详细解析"
        }
      ]
    }
    不要包含任何其他解释文字。
    """
    
    # 将文字加入消息
    message_content.append({"type": "text", "text": text_prompt})
    
    payload = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "user", "content": message_content}
        ],
        "temperature": 0.7,
        "max_tokens": 4000
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    
    try:
        response = requests.post(API_URL, json=payload, headers=headers)
        response.raise_for_status()
        content = response.json()['choices'][0]['message']['content']
        return json.loads(clean_json_response(content)).get("questions", [])
    except Exception as e:
        print(f"API Error: {e}")
        return []

def build_full_exam(api_key, subject, difficulty, time_limit):
    """根据时间限制组卷"""
    target_mcq = time_limit  
    target_essay = time_limit // 30  
    
    all_questions = []
    progress_bar = st.progress(0.0)
    status_text = st.empty()
    
    chunk_size = 5 # 每批次生成5题，保证输出稳定不截断
    total_chunks = math.ceil(target_mcq / chunk_size)
    
    essays_generated = 0
    images_generated = 0
    
    for i in range(total_chunks):
        status_text.markdown(f"**AI老师正在看图出题中... (第 {i+1}/{total_chunks} 批次)**\n\n*请稍候，马上就好。*")
        
        current_mcq_count = chunk_size if (i + 1) < total_chunks else target_mcq - (i * chunk_size)
        current_essay_count = 1 if essays_generated < target_essay else 0
        if current_essay_count > 0: essays_generated += 1
        
        # 过滤对应学科的图片
        valid_images = [img for img in IMAGE_LIBRARY if subject == "地理生物综合" or img["subject"] in subject]
                
        image_info = None
        if valid_images and images_generated < (time_limit // 15) and random.choice([True, False]):
            image_info = random.choice(valid_images)
            images_generated += 1
            current_mcq_count -= 1 
            
        chunk_qs = generate_questions_chunk(api_key, subject, difficulty, current_mcq_count, current_essay_count, image_info)
        
        if image_info:
            for q in chunk_qs:
                if q.get('type') == 'image_recognition':
                    q['image_path'] = image_info['path']
        
        all_questions.extend(chunk_qs)
        progress_bar.progress((i + 1) / total_chunks)
        
    # 重新编号
    for idx, q in enumerate(all_questions):
        q['id'] = idx + 1
        
    status_text.empty()
    progress_bar.empty()
    
    return {
        "paper_title": f"{subject} - {difficulty}测试 ({time_limit}分钟)",
        "questions": all_questions
    }

def grade_essay(api_key, question, standard_answer, user_answer):
    """AI 论述题阅卷"""
    if not user_answer.strip(): return 0, "未作答。"
    prompt = f"请根据标准答案为论述题打分（满分10分）。\n题目：{question}\n标答：{standard_answer}\n学生：{user_answer}\n返回JSON：{{\"score\": 数字, \"comment\": \"评价\"}}"
    payload = {"model": MODEL_NAME, "messages": [{"role": "user", "content": prompt}], "temperature": 0.3}
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
        response = requests.post(API_URL, json=payload, headers=headers)
        result = json.loads(clean_json_response(response.json()['choices'][0]['message']['content']))
        return result.get('score', 0), result.get('comment', '')
    except:
        return 5, "AI评分失败，给予默认及格分。"

# ================= 5. 页面视图呈现 =================
st.set_page_config(page_title="地生万物 - 智能学习系统", layout="centered")

with st.sidebar:
    st.title("🌱 地生万物")
    api_key = st.text_input("输入 SiliconFlow API Key", type="password")
    st.markdown("---")
    st.metric("🏆 累计积分", f"{st.session_state.total_points:.0f}")

if st.session_state.page == 'home':
    st.header("📝 考试配置")
    subject = st.selectbox("选择学科", ["地理生物综合", "初中地理", "初中生物"])
    difficulty = st.select_slider("选择难度", options=list(DIFFICULTY_SETTINGS.keys()))
    time_limit = st.selectbox("时间限制", [30, 60, 90, 120], format_func=lambda x: f"{x} 分钟")
    
    if st.button("🚀 开始生成试卷", use_container_width=True):
        if not api_key: st.warning("请先在左侧输入 API Key！")
        else:
            exam_data = build_full_exam(api_key, subject, difficulty, time_limit)
            if exam_data and len(exam_data['questions']) > 0:
                st.session_state.exam_data = exam_data
                st.session_state.difficulty = difficulty
                st.session_state.time_limit_mins = time_limit
                st.session_state.start_time = time.time()
                st.session_state.user_answers = {}
                st.session_state.page = 'exam'
                st.rerun()
            else:
                st.error("生成失败，请检查网络或点击重试。")

elif st.session_state.page == 'exam':
    exam = st.session_state.exam_data
    st.header(exam.get("paper_title", "综合测试"))
    
    remaining_time = (st.session_state.time_limit_mins * 60) - (time.time() - st.session_state.start_time)
    if remaining_time <= 0:
        st.error("时间到！系统已自动强制交卷。")
        st.session_state.page = 'result'
        st.rerun()
    else:
        mins, secs = divmod(int(remaining_time), 60)
        st.info(f"⏳ 剩余时间: {mins}分 {secs}秒")

    with st.form("exam_form"):
        for q in exam['questions']:
            q_id = str(q['id'])
            st.markdown(f"**第 {q_id} 题**")
            
            if q.get('type') == 'image_recognition' and 'image_path' in q:
                if os.path.exists(q['image_path']):
                    st.image(q['image_path'], use_container_width=True)
            
            st.write(q['question'])
            
            if q.get('type') in ['choice', 'image_recognition']:
                options = [f"{k}: {v}" for k, v in q.get('options', {}).items()]
                choice = st.radio("请选择:", options, index=None, key=f"q_{q_id}")
                if choice: st.session_state.user_answers[q_id] = choice.split(":")[0]
            elif q.get('type') == 'essay':
                st.session_state.user_answers[q_id] = st.text_area("请输入你的论述:", height=150, key=f"q_{q_id}")
            st.markdown("---")
            
        if st.form_submit_button("✅ 提交试卷", use_container_width=True):
            st.session_state.page = 'result'
            st.rerun()

elif st.session_state.page == 'result':
    st.header("📊 考试结果与解析")
    exam = st.session_state.exam_data
    answers = st.session_state.user_answers
    total_score = 0
    max_score = len(exam['questions']) * 10 
    
    with st.spinner("AI 老师阅卷中..."):
        for q in exam['questions']:
            q_id = str(q['id'])
            user_ans = answers.get(q_id, "")
            with st.expander(f"第 {q_id} 题解析", expanded=False):
                if q.get('type') == 'image_recognition' and 'image_path' in q and os.path.exists(q['image_path']):
                     st.image(q['image_path'], width=300)
                st.write(f"**题目:** {q['question']}")
                
                if q.get('type') in ['choice', 'image_recognition']:
                    st.write(f"你的答案: {user_ans} | 标准答案: {q.get('answer')}")
                    if user_ans == q.get('answer'):
                        st.success("回答正确！得 10 分"); total_score += 10
                    else: st.error("回答错误！得 0 分")
                    st.info(f"**解析:** {q.get('explanation')}")
                elif q.get('type') == 'essay':
                    st.write(f"你的论述: {user_ans}")
                    score, comment = grade_essay(api_key, q['question'], q.get('answer', ''), user_ans)
                    total_score += score
                    st.success(f"AI 评分: {score}/10 分") if score >= 6 else st.warning(f"AI 评分: {score}/10 分")
                    st.info(f"**评价:** {comment}\n\n**考点:** {q.get('explanation')}")

    coeff = DIFFICULTY_SETTINGS[st.session_state.difficulty]['coeff']
    earned_points = (total_score / max_score) * 100 * coeff if max_score > 0 else 0
    st.session_state.total_points += earned_points
    
    st.markdown("### 🏆 成绩结算")
    col1, col2, col3 = st.columns(3)
    col1.metric("得分", f"{total_score} / {max_score}")
    col2.metric("难度系数", f"x {coeff}")
    col3.metric("获得积分", f"+{earned_points:.0f}")
    
    if st.button("🏠 返回主页", use_container_width=True):
        st.session_state.page = 'home'
        st.session_state.exam_data = None
        st.rerun()
