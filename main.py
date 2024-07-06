# ... (前面的導入和設置保持不變)

def generate_scam_example():
    template = random.choice(scam_templates)
    prompt = (
        f"以下是一個詐騙訊息範例:\n\n{template}\n\n"
        "請根據這個範例生成一個新的、類似的詐騙訊息。保持相似的結構和風格，"
        "但改變具體內容。請確保新生成的訊息具有教育性質，可以用於提高人們對詐騙的警惕性。"
        "只需要生成詐騙訊息本身，不要添加任何額外的說明或指示。"
    )
    
    model = genai.GenerativeModel('gemini-pro')
    response = model.generate_content(prompt)
    return response.text.strip()

def analyze_response(text):
    prompt = (
        f"以下是一個潛在的詐騙訊息:\n\n{text}\n\n"
        "請分析這條訊息，並提供詳細的辨別建議。包括以下幾點：\n"
        "1. 這條訊息中的可疑元素\n"
        "2. 為什麼這些元素是可疑的\n"
        "3. 如何識別類似的詐騙訊息\n"
        "4. 面對這種訊息時應該採取什麼行動\n"
        "請以教育性和提醒性的語氣回答，幫助人們提高警惕。不要使用粗體或任何特殊格式，只需使用純文本。不要使用破折號，而是使用數字列表。"
    )
    
    model = genai.GenerativeModel('gemini-pro')
    response = model.generate_content(prompt)
    return response.text.strip()

@app.post("/webhooks/line")
async def handle_callback(request: Request):
    # ... (前面的代碼保持不變)

    for event in events:
        # ... (事件處理的開始部分保持不變)

        if text == "出題":
            scam_example = generate_scam_example()
            messages = [{'role': 'bot', 'parts': [scam_example]}]
            fdb.put_async(user_chat_path, None, messages)
            reply_msg = scam_example
        elif text == "解析":
            if chatgpt and len(chatgpt) > 0 and chatgpt[-1]['role'] == 'bot':
                scam_message = chatgpt[-1]['parts'][0]
                advice = analyze_response(scam_message)
                reply_msg = f'詐騙訊息分析:\n\n{advice}'
            else:
                reply_msg = '目前沒有可供解析的訊息，請先輸入「出題」生成一個範例。'
        else:
            reply_msg = '未能識別的指令，請輸入「出題」生成一個詐騙訊息範例，或輸入「解析」來分析上一個生成的範例。'

        await line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_msg)]
            ))

    return 'OK'

# ... (其餘的代碼保持不變)
