# PostgreSQL وAlembic في Awesome Blog

يوضح هذا الدليل إعداد قاعدة البيانات وطريقة تطبيق تغييرات المخطط. التطبيق يستخدم PostgreSQL؛ إنشاء الجداول وتحديثها يتمان عبر Alembic بدل إنشاء الجداول تلقائيًا عند بدء FastAPI.

## الملفات والمسؤوليات

| الملف | دوره |
| --- | --- |
| `requirements.txt` | يثبت `asyncpg` للاتصال غير المتزامن بـPostgreSQL و`alembic` لإدارة المهاجرات. |
| `.env.example` | مثال لإعداد اسم قاعدة البيانات والمستخدم وكلمة المرور ورابط الاتصال ومنافذ التشغيل. |
| `compose.yaml` | يشغّل قاعدة البيانات، ينتظر جاهزيتها، يطبق المهاجرات، ثم يبدأ التطبيق. |
| `app/core/database.py` | يبني SQLAlchemy async engine وsessions من `DATABASE_URL`. |
| `app/core/lifespan.py` | ينهي اتصالات قاعدة البيانات عند إيقاف التطبيق؛ لا ينشئ الجداول. |
| `alembic.ini` | يحدد مجلد إعدادات Alembic وموقع ملفات المهاجرات. |
| `alembic/env.py` | يقرأ `DATABASE_URL`، ويسجل نماذج SQLAlchemy، ويشغّل Alembic باستخدام اتصال async. |
| `alembic/versions/0001_initial_schema.py` | ينشئ المخطط الأولي للجداول والفهارس والقيود. |

المهاجرة الأولية تنشئ جداول `users` و`posts` و`refresh_tokens` و`revoked_tokens`، بالإضافة إلى جدول Alembic الذي يتتبع آخر إصدار مطبّق.

## إعداد الاتصال

ابدأ بإنشاء `.env` من المثال إن لم يكن موجودًا:

```bash
cp .env.example .env
```

اضبط `POSTGRES_DB` و`POSTGRES_USER` و`POSTGRES_PASSWORD`. كلمة المرور تُستخدم داخل رابط اتصال، لذلك اجعلها URL-safe أو شفّر الرموز الخاصة فيها. `DATABASE_URL` مخصص للأدوات التي تعمل على الجهاز المضيف؛ في Compose يستبدل التطبيق وعامل المهاجرات هذا الرابط بعنوان الخدمة `db` داخل شبكة Docker.

ملف `.env` الحقيقي مستبعد من Git وصورة Docker. لا تضع كلمة مرور حقيقية في `.env.example` أو في ملفات المهاجرات.

## ترتيب التشغيل في Compose

عند تنفيذ:

```bash
docker compose up --build -d --wait
```

يحدث الآتي بالترتيب:

1. يبدأ PostgreSQL، ويستخدم فحص `pg_isready` حتى تصبح قاعدة البيانات جاهزة.
2. تشغّل خدمة `migrate` الأمر `alembic upgrade head`.
3. لا تبدأ خدمة `web` حتى تنتهي خدمة المهاجرات بنجاح.
4. يبدأ Uvicorn، ويتحقق healthcheck من استجابة الـAPI واتصاله بقاعدة البيانات.

بيانات PostgreSQL تحفظ في volume اسمه `awesome-blog_postgres_data`، والصور المرفوعة تحفظ في `awesome-blog_blog_media`. أمر `docker compose down` يوقف الخدمات مع الإبقاء على البيانات؛ `docker compose down --volumes` يحذفها.

## تطوير المخطط

بعد تعديل نموذج SQLAlchemy، شغّل قاعدة البيانات أولًا إذا كنت تعمل من الجهاز المضيف، ثم أنشئ مسودة migration:

```bash
docker compose up -d db
alembic revision --autogenerate -m "describe the schema change"
```

راجع الملف الجديد في `alembic/versions/` وعدّله عند الحاجة. `--autogenerate` يقارن النماذج بقاعدة البيانات، لكنه لا يضمن أن التغيير آمن أو كامل.

طبّق المهاجرات يدويًا أثناء التطوير:

```bash
alembic upgrade head
```

في Docker، أعد بناء وتشغيل الخدمات؛ Compose يشغّل أمر Alembic قبل التطبيق، ويطبق الإصدارات غير المنفذة فقط.

لعرض حالة المخطط:

```bash
alembic current
alembic history
```

يمكن الرجوع عن مهاجرة واحدة باستخدام:

```bash
alembic downgrade -1
```

راجع `downgrade()` قبل تشغيله على بيانات مهمة؛ الرجوع قد يحذف أعمدة أو جداول وبيانات.

## نقل بيانات SQLite القديمة

تغيير التطبيق إلى PostgreSQL لا ينقل محتوى `blog.db` القديم تلقائيًا. قاعدة PostgreSQL تبدأ بمخطط جديد؛ احتفظ بنسخة من قاعدة SQLite، ثم استخدم أداة ترحيل بيانات مناسبة قبل تحويل المستخدمين أو المنشورات. لا تحذف volume القديم قبل التأكد من اكتمال النقل.

## الاختبارات

اعتماد SQLite موجود في `requirements-dev.txt` فقط لتشغيل الاختبارات الحالية بقاعدة معزولة. صورة التطبيق واعتماديات التشغيل تستخدم PostgreSQL و`asyncpg`.

شرح التشغيل اليومي وأوامر Docker موجود في [DOCKER_AR.md](DOCKER_AR.md)، وشرح المصادقة عبر الـAPI في [AUTHENTICATION_AR.md](AUTHENTICATION_AR.md).
