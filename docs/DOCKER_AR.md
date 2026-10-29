# PostgreSQL وAlembic باستخدام Docker

Compose يشغّل PostgreSQL 17، وينفّذ مهاجرات Alembic قبل تشغيل FastAPI. قاعدة البيانات والصور محفوظتان في volumes مستقلين عن الحاويات. لم يعد التطبيق ينشئ الجداول تلقائيًا؛ كل تغيير في المخطط يمر عبر migration.

لشرح ملفات الإعداد والمهاجرات خطوة بخطوة، راجع [دليل PostgreSQL وAlembic](POSTGRESQL_ALEMBIC_AR.md).

## الإعداد والتشغيل

لو `.env` مش موجود، أنشئه من المثال:

```bash
test -f .env || cp .env.example .env
```

غيّر `POSTGRES_PASSWORD` إلى كلمة مرور طويلة وآمنة ومناسبة للاستخدام داخل URL، وحدد `JWT_SECRET_KEY` بقيمة عشوائية لا تقل عن 32 حرفًا. حافظ على تطابق كلمة مرور PostgreSQL في `DATABASE_URL` للتشغيل المحلي. ملف `.env` الحقيقي مستبعد من صورة Docker ومستودع Git.

| المتغير | الاستخدام |
| --- | --- |
| `POSTGRES_DB` | اسم قاعدة البيانات. |
| `POSTGRES_USER` | مستخدم PostgreSQL. |
| `POSTGRES_PASSWORD` | كلمة مرور المستخدم، ويجب أن تكون URL-safe حتى تدخل في رابط الاتصال. |
| `DATABASE_URL` | اتصال PostgreSQL من جهاز المطور على `localhost`. |
| `POSTGRES_PORT` | منفذ PostgreSQL على الجهاز، افتراضيًا 5432. |
| `BLOG_PORT` | منفذ واجهة التطبيق، افتراضيًا 8082. |
| `JWT_SECRET_KEY` | مفتاح توقيع التوكنات. |
| `JWT_ACCESS_TOKEN_MINUTES` | مدة صلاحية Access Token بالدقائق. |
| `REFRESH_TOKEN_DAYS` | الحد الأقصى لعمر جلسة التجديد بالأيام. |

ابدأ الخدمات والمهاجرات:

```bash
docker compose config --quiet
docker compose up --build -d --wait
```

التطبيق متاح على `http://localhost:8082`، وتوثيق API على `/docs`، وفحص الجاهزية على `/health`. الخدمة تنتظر أن تصبح PostgreSQL جاهزة، ثم تنتظر نجاح `alembic upgrade head` قبل تشغيل Uvicorn.

لتشغيل FastAPI خارج Docker مع قاعدة البيانات التي يديرها Compose، استخدم `DATABASE_URL` كما هو في `.env` بعد تشغيل خدمة قاعدة البيانات:

```bash
docker compose up -d db
uvicorn app.main:app --reload
```

## إدارة المهاجرات

أنشئ migration بعد تعديل نماذج SQLAlchemy:

```bash
alembic revision --autogenerate -m "describe schema change"
```

راجع ملف migration الناتج وعدّله عند الحاجة، ثم طبّقه محليًا:

```bash
alembic upgrade head
```

للتراجع عن migration واحدة:

```bash
alembic downgrade -1
```

عند نشر migration جديدة، إعادة بناء التطبيق وتشغيل Compose تعيد تنفيذ الأمر بأمان؛ Alembic يطبق فقط المهاجرات غير المسجلة. لا تستخدم `Base.metadata.create_all()` لتحديث قواعد بيانات الإنتاج.

## البيانات والتشغيل

| Volume | المحتوى |
| --- | --- |
| `postgres_data` | ملفات PostgreSQL وقاعدة التطبيق. |
| `blog_media` | صور الملفات الشخصية المرفوعة. |

`docker compose down` يوقف الحاويات مع الاحتفاظ بالبيانات. `docker compose down --volumes` يحذف قاعدة البيانات والصور بشكل نهائي.

قاعدة `blog.db` المحلية القديمة لا تُنقل تلقائيًا إلى PostgreSQL؛ أول تشغيل يبدأ قاعدة PostgreSQL جديدة. صدّر البيانات واستوردها بأداة مناسبة قبل التحويل إذا كانت لديك بيانات تريد الاحتفاظ بها.

```bash
docker compose ps
docker compose logs -f web
docker compose logs migrate
```

مفتاح JWT وكلمة مرور قاعدة البيانات يُقرآن وقت التشغيل ولا يضافان إلى صورة التطبيق. استخدم مدير أسرار مناسبًا بدل ملف `.env` عند النشر الفعلي، وخذ نسخًا احتياطية منتظمة من PostgreSQL volume.

التطبيق وصورة الإنتاج يستخدمان PostgreSQL فقط. الاختبارات الحالية تستخدم SQLite معزولة محليًا، وثبّت متطلباتها الاختيارية عبر `pip install -r requirements-dev.txt`.
