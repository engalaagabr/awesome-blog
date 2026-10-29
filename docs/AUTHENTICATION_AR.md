# المصادقة في الـAPI

المسارات المحمية تقبل جلسة `blog_session` من Cookie أو Access Token في ترويسة Bearer. تسجيل الدخول ينشئ Access Token وRefresh Token؛ صلاحية جلسة التجديد محددة من البداية، وتدوير Refresh Token لا يمدد عمر الجلسة.

## تسجيل الدخول واستخدام Cookie

احفظ ملفات Cookie عند تسجيل الدخول وأرسلها مع الطلبات التالية:

```bash
curl -i -c cookies.txt \
  -H 'Content-Type: application/json' \
  -d '{"username":"alice","password":"Password1"}' \
  http://localhost:8082/api/users/login

curl -b cookies.txt http://localhost:8082/api/users/me
```

الـCookies من نوع HttpOnly وSameSite=Lax، ويُفعّل Secure عند استخدام HTTPS. طلبات الكتابة المعتمدة على Cookie تتحقق من أن الـOrigin يطابق أصل التطبيق.

## استخدام Bearer Token

استخرج `access_token` من رد تسجيل الدخول وأرسله في الترويسة:

```bash
curl -H 'Authorization: Bearer ACCESS_TOKEN' \
  http://localhost:8082/api/users/me
```

لا تضع التوكن الحقيقي في ملفات المشروع أو سجل الأوامر المشترك.

## تجديد الجلسة وإنهاؤها

مع Cookie، أرسل `POST /api/users/refresh`؛ سيعيد الخادم تدوير التوكنات وتحديث Cookie. عملاء API الذين يخزنون التوكنات بأنفسهم يرسلون `refresh_token` في JSON ويستبدلون الزوج كاملًا بالزوج المعاد:

```json
{"refresh_token":"CURRENT_REFRESH_TOKEN"}
```

إعادة استخدام Refresh Token سبق تدويره تلغي الجلسة المرتبطة به. لإنهاء الجلسة أرسل `POST /api/users/logout`. يمكن لعميل API إرسال Refresh Token في جسم الطلب إذا لم تعد لديه Cookie أو انتهت صلاحية Access Token.

## إعداد المفتاح

أنشئ `JWT_SECRET_KEY` عشوائيًا بطول 32 حرفًا على الأقل وخزّنه في `.env` محليًا أو في مدير أسرار عند النشر. لا تضع سرًا حقيقيًا في `.env.example` أو المستودع.
