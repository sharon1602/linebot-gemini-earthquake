from fastapi import FastAPI, HTTPException, Request
import logging
import os
import sys
from dotenv import load_dotenv
from linebot import (
    LineBotApi, WebhookParser
)
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage, ConfirmTemplate, MessageAction, TemplateSendMessage
)
from firebase import firebase
import random
import uvicorn
import google.generativeai as genai

logging.basicConfig(level=os.getenv('LOG', 'WARNING'))
logger = logging.getLogger(__file__)

app = FastAPI()

load_dotenv()
channel_secret = os.getenv('LINE_CHANNEL_SECRET', None)
channel_access_token = os.getenv('LINE_CHANNEL_ACCESS_TOKEN', None)
if channel_secret is None or channel_access_token is None:
    logger.error('Specify LINE_CHANNEL_SECRET and LINE_CHANNEL_ACCESS_TOKEN as environment variables.')
    sys.exit(1)

line_bot_api = LineBotApi(channel_access_token)
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
        if not isinstance(event, MessageEvent) or not isinstance(event.message, TextMessage):
            continue

        user_id = event.source.user_id
        fdb = firebase.FirebaseApplication(firebase_url, None)
        user_score_path = f'scores/{user_id}'
        user_score = fdb.get(user_score_path, None) or 0

        if event.message.text == '出題':
            scam_example, correct_example = generate_examples()
            messages = [{'role': 'bot', 'parts': [scam_example, correct_example]}]
            fdb.put_async(f'chat/{user_id}', None, messages)
            reply_msg = f"{scam_example}\n\n請判斷這是否為詐騙訊息"
            confirm_template = ConfirmTemplate(
                text='請判斷是否為詐騙訊息。',
                actions=[
                    MessageAction(label='是', text='是'),
                    MessageAction(label='否', text='否')
                ]
            )
            template_message = TemplateSendMessage(alt_text='出題', template=confirm_template)
            line_bot_api.reply_message(event.reply_token, [TextSendMessage(text=reply_msg), template_message])
        elif event.message.text == '分數':
            reply_msg = f"你的當前分數是：{user_score}分"
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_msg))
        elif event.message.text == "解析":
            chatgpt = fdb.get(f'chat/{user_id}', None)
            if chatgpt and len(chatgpt) > 0 and chatgpt[-1]['role'] == 'bot':
                message = chatgpt[-1]['parts'][0]
                is_scam = chatgpt[-1]['is_scam']
                advice = analyze_response(message, is_scam, is_scam)
                reply_msg = f"這是{'詐騙' if is_scam else '正確'}訊息。分析如下:\n\n{advice}"
            else:
                reply_msg = '目前沒有可供解析的訊息，請先輸入「出題」生成一個範例。'
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_msg))
        elif event.message.text in ['是', '否']:
            chatgpt = fdb.get(f'chat/{user_id}', None)
            if chatgpt and len(chatgpt) > 0 and chatgpt[-1]['role'] == 'bot':
                scam_message, correct_message = chatgpt[-1]['parts']
                is_scam = scam_message is not None
                user_response = event.message.text == '是'

                if user_response == is_scam:
                    user_score += 50
                else:
                    user_score -= 50
                    advice = analyze_response(scam_message if is_scam else correct_message, is_scam, user_response)
                    reply_msg = f"這是{'詐騙' if is_scam else '正確'}訊息。分析如下:\n\n{advice}\n\n你的當前分數是：{user_score}分"
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_msg))

                fdb.put_async(user_score_path, None, user_score)
                reply_msg = f"你的當前分數是：{user_score}分"
            else:
                reply_msg = '目前沒有可供解析的訊息，請先輸入「出題」生成一個範例。'
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_msg))
        else:
            reply_msg = '請先回答「是」或「否」來判斷詐騙訊息，再查看解析。'
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_msg))

    return 'OK'

def generate_examples():
    scam_template = random.choice(scam_templates)
    prompt_scam = (
        f"以下是一個詐騙訊息範例:\n\n{scam_template}\n\n"
        "請根據這個範例生成一個新的、類似的詐騙訊息。保持相似的結構和風格，"
        "但改變具體內容。請確保新生成的訊息具有教育性質，可以用於提高人們對詐騙的警惕性。"
        "只需要生成詐騙訊息本身，不要添加任何額外的說明或指示。"
    )
    prompt_correct = (
        "這是一個合法的範例訊息，請根據上面的詐騙訊息範例生成一個與之類似但是合法的範例訊息。"
        "保持相似的結構和風格，但改變具體內容。只需要生成正確訊息本身，不要添加任何額外的說明或指示。"
    )

    return prompt_scam, prompt_correct

def analyze_response(message, is_scam, user_response):
    if is_scam:
        if user_response:
            return "這確實是一條詐騙訊息。建議永遠不要點擊訊息中的連結，並且可以通過報告詐騙行為來保護自己和他人。"
        else:
            return "這不是詐騙訊息，但這條訊息具有一些可能令人懷疑的特徵。建議保持警惕，避免與此類訊息交互。"
    else:
        if user_response:
            return "這是一條合法的訊息，沒有任何詐騙行為跡象。請繼續保持警惕，但可以安全地與這條訊息進行互動。"
        else:
            return "這不是詐騙訊息，並且沒有任何可能令人懷疑的特徵。請繼續保持警惕，但可以安全地與這條訊息進行互動。"

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
