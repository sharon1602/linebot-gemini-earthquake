from fastapi import FastAPI, HTTPException, Request
import logging
import os
import sys
from datetime import datetime
from dotenv import load_dotenv
from linebot.v3.webhook import WebhookParser
from linebot.v3.messaging import (
    AsyncApiClient,
    AsyncMessagingApi,
    Configuration,
    ReplyMessageRequest,
    TextMessage
)
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.webhooks import MessageEvent, TextMessageContent

import uvicorn
import google.generativeai as genai
from firebase import firebase
import random

logging.basicConfig(level=os.getenv('LOG', 'WARNING'))
logger = logging.getLogger(__file__)

app = FastAPI()

load_dotenv()
channel_secret = os.getenv('LINE_CHANNEL_SECRET', None)
channel_access_token = os.getenv('LINE_CHANNEL_ACCESS_TOKEN', None)
if channel_secret is None:
    print('Specify LINE_CHANNEL_SECRET as environment variable.')
    sys.exit(1)
if channel_access_token is None:
    print('Specify LINE_CHANNEL_ACCESS_TOKEN as環境變數.')
    sys.exit(1)

configuration = Configuration(access_token=channel_access_token)
async_api_client = AsyncApiClient(configuration)
line_bot_api = AsyncMessagingApi(async_api_client)
parser = WebhookParser(channel_secret)

firebase_url = os.getenv('FIREBASE_URL')
gemini_key = os.getenv('GEMINI_API_KEY')
genai.configure(api_key=gemini_key)

scam_templates = [
    "【國泰世華】您的銀行賬戶顯示異常，請立即登入綁定用戶資料，否則賬戶將凍結使用 www.cathay-bk.com",
    "我朋友參加攝影比賽麻煩幫忙投票 http://www.yahoonikk.info/page/vote.pgp?pid=51",
    "登入FB就投票成功了我手機當機 line用不了 想請你幫忙安全認證 幫我收個認證簡訊 謝謝 你LINE的登陸認證密碼記得嗎 認證要用到 確認是本人幫忙認證",
    "您的LINE已違規使用，將在24小時內註銷，請使用谷歌瀏覽器登入電腦網站並掃碼驗證解除違規 www.line-wbe.icu",
    "【台灣自來水公司】貴戶本期水費已逾期，總計新台幣395元整，務請於6月16日前處理繳費，詳情繳費：https://bit.ly/4cnMNtE 若再超過上述日期，將終止供水",
    "萬聖節快樂🎃 活動免費貼圖無限量下載 https://lineeshop.com",
    "【台灣電力股份有限公司】貴戶本期電費已逾期，總計新台幣1058元整，務請於6月14日前處理繳費，詳情繳費：(網址)，若再超過上述日期，將停止收費"
]
real_templates = [
    "Gap夏季盛典⭐全面4折起⭐上班穿搭從容通勤，下班換上神短褲🩳到LINE查詢會員點數抵消費 https://maac.io/20nHK",
    "【中華電信網路門市優惠通知】3月起精彩運動賽事BWF全英公開賽、MLB等即將開打！Hami Video影視雙享包含超過100個頻道(運動、新聞、生活等)+萬部電影、戲劇，每月僅$188起，最高再贈8GB/月上網量！追劇好康雙享不錯過，立即了解→ https://cht.tw/x/5qud8",
    "【momo年末應援】有錢快領100元購物金！全館商品現折$100，提醒購物金效期有限，手刀搶購 https://momo.dm/uVbyf3",
    "警政署提醒您，詐團盜用名人照片投放投資廣告吸引加LINE群組，群組成員多為詐團暗樁，切勿輕易相信，詳見：165.npa.gov.tw。",
    "9/14起中友購物節全館滿仟贈點！獨享會員禮、15大指定銀行刷卡禮、扣10點抽百萬經典豪車！ https://reurl.cc/jvq99D",
    "【恭喜您獲得加碼資格！】感謝您使用台新信用卡，請於收到本簡訊3天內首登Richart Life APP tsbk.tw/3z7vxy/ 點擊「我的」>「輸入推薦碼」輸入「CARD30」即贈限量刷卡金30元！謹慎理財信用至上循環利率6.75%-15%",
    "【跨年LINE POINTS一把抓】貼圖、美食優惠券，完成任務讓你點數領不完，都在台新LINE https://tsbk.tw/5fnvc9"
]

@app.get("/health")
async def health():
    return 'ok'

@app.post("/webhooks/line")
async def handle_callback(request: Request):
    signature = request.headers['X-Line-Signature']

    body = await request.body()
    body = body.decode()

    try:
        events = parser.parse(body, signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    for event in events:
        logging.info(event)
        if not isinstance(event, MessageEvent):
            continue
        if not isinstance(event.message, TextMessageContent):
            continue
        text = event.message.text.strip()
        user_id = event.source.user_id

        fdb = firebase.FirebaseApplication(firebase_url, None)
        if event.source.type == 'group':
            user_chat_path = f'chat/{event.source.group_id}'
        else:
            user_chat_path = f'chat/{user_id}'
        chatgpt = fdb.get(user_chat_path, None)

        user_score_path = f'scores/{user_id}'
        user_score = fdb.get(user_score_path, None) or 0

        if text == "出題":
            scam_example, correct_example = generate_examples()
            is_scam = random.choice([True, False])
            if is_scam:
                message = scam_example
            else:
                message = correct_example
            messages = [{'role': 'bot', 'parts': [message], 'is_scam': is_scam}]
            fdb.put_async(user_chat_path, None, messages)
            reply_msg = f"{message}\n\n請判斷這是否為詐騙訊息（請回覆'是'或'否')❗️❗️"
        elif text == "分數":
            reply_msg = f"你的當前分數是：{user_score}分 👍"
        elif text == "解析":
            if chatgpt and len(chatgpt) > 0 and chatgpt[-1]['role'] == 'bot':
                message = chatgpt[-1]['parts'][0]
                is_scam = chatgpt[-1]['is_scam']
                advice = analyze_response(message, is_scam, is_scam)
                reply_msg = f"這是{'詐騙' if is_scam else '正確'}訊息。❗️\n如下:\n\n{advice}"
            else:
                reply_msg = '目前沒有可供解析的訊息，請先輸入「出題」生成一個範例。'
        elif text in ["是", "否"]:
            if chatgpt and len(chatgpt) > 0 and chatgpt[-1]['role'] == 'bot':
                message = chatgpt[-1]['parts'][0]
                is_scam = chatgpt[-1]['is_scam']
                user_response = text == "是"
                
                if user_response == is_scam:
                    user_score += 50
                    fdb.put_async(user_score_path, None, user_score)
                    reply_msg = f"你好棒！🥳 你的當前分數是：{user_score}分❗️"
                else:
                    if user_score < 50:
                        reply_msg = "您目前分數為0分！請加油！🥺"
                    else:
                        user_score -= 50
                        fdb.put_async(user_score_path, None, user_score)
                        advice = analyze_response(message, is_scam, user_response)
                        reply_msg = f"這是{'詐騙' if is_scam else '正確'}訊息。分析如下:\n\n{advice}\n\n你的當前分數是：{user_score}分"
            else:
                reply_msg = '目前沒有可供解析的訊息，請先輸入「出題」生成一個範例。'
        else:
            reply_msg = '未能識別的指令，請輸入「出題」生成一個詐騙訊息範例，或輸入「是」或「否」來判斷上一個生成的範例。'

        await line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_msg)]
            ))

    return 'OK'


def generate_examples():
    prompt_scam = (
        "請以{random.choice(scam_templates)}作為範例生成一個詐騙訊息範例。請注意，這條訊息應該是以詐騙為目的，並包含誘導性、虛假或令人感到緊急的內容，"
        "例如銀行詐騙、假冒官員、假冒朋友等。這條訊息將用於教育和提醒人們如何辨別詐騙訊息。\n\n"
        f"{random.choice(scam_templates)}"
    )
    prompt_correct = (
        "請以{random.choice(real_templates)}作為範例生成一個真實且正確的訊息範例。請確保這條訊息與下列真實訊息範例相似，但內容必須是真實且正確的，"
        "例如商家促銷、官方公告或其他合法的信息。請確保生成的訊息能夠用於教育和提醒人們如何辨別真實信息。\n\n"
       
    )
    model = genai.GenerativeModel('gemini-pro')
    scam_example = model.generate_content(prompt_scam).text.strip()
    correct_example = model.generate_content(prompt_correct).text.strip()
    return scam_example, correct_example

def analyze_response(text, is_scam, user_response):
    if user_response == is_scam:
        # 如果用户回答正确
        if is_scam:
            prompt = (
                f"以下是一個詐騙訊息:\n\n{text}\n\n"
                "請分析這條訊息，並提供詳細的辨別建議。包括以下幾點：\n"
                "1. 這條訊息中的可疑元素\n"
                "2. 為什麼這些元素是可疑的\n"
                "3. 如何識別類似的詐騙訊息\n"
                "4. 面對這種訊息時應該採取什麼行動\n"
                "請以教育性和提醒性的語氣回答，幫助人們提高警惕。"
                "不要使用任何粗體或任何特殊格式，例如＊或是-，不要使用markdown語法，只需使用純文本。不要使用破折號，而是使用數字列表。"
            )
        else:
            prompt = (
                f"以下是一個真實且正確的訊息:\n\n{text}\n\n"
                "請分析這條訊息，並提供詳細的辨別建議。包括以下幾點：\n"
                "1. 這條訊息中的真實元素\n"
                "2. 為什麼這些元素是真實的\n"
                "3. 如何識別類似的真實訊息\n"
                "4. 面對這種訊息時應該採取什麼行動\n"
                "請以教育性和提醒性的語氣回答，幫助人們提高對真實訊息的識別能力。"
                "不要使用任何粗體或任何特殊格式，例如＊或是-，不要使用markdown語法，只需使用純文本。不要使用破折號，而是使用數字列表。"
            )
    else:
        # 如果用户回答错误
        if is_scam:
            prompt = (
                f"以下是一個詐騙訊息:\n\n{text}\n\n"
                "用戶認為這不是詐騙訊息。請分析這條訊息，並提供詳細的辨別建議。包括以下幾點：\n"
                "1. 這條訊息中的可疑元素\n"
                "2. 為什麼這些元素是可疑的\n"
                "3. 如何識別類似的詐騙訊息\n"
                "4. 面對這種訊息時應該採取什麼行動\n"
                "請以教育性和提醒性的語氣回答，幫助人們提高警惕。"
                "不要使用任何粗體或任何特殊格式，例如＊或是-，不要使用markdown語法，只需使用純文本。不要使用破折號，而是使用數字列表。"
            )
        else:
            prompt = (
                f"以下是一個真實且正確的訊息:\n\n{text}\n\n"
                "用戶認為這是詐騙訊息。請分析這條訊息，並提供詳細的辨別建議。包括以下幾點：\n"
                "1. 這條訊息中的真實元素\n"
                "2. 為什麼這些元素是真實的\n"
                "3. 如何識別類似的真實訊息\n"
                "4. 面對這種訊息時應該採取什麼行動\n"
                "請以教育性和提醒性的語氣回答，幫助人們提高對真實訊息的識別能力。"
                "不要使用任何粗體或任何特殊格式，例如＊或是-，不要使用markdown語法，只需使用純文本。不要使用破折號，而是使用數字列表。"
            )

    model = genai.GenerativeModel('gemini-pro')
    response = model.generate_content(prompt)
    return response.text.strip()

if __name__ == "__main__":
    port = int(os.getenv('PORT', 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
