# تشغيل FastAPI Blog باستخدام Docker

ملف `Dockerfile` بيجهز التطبيق باستخدام Python 3.14، و`compose.yaml` بيقرأ إعدادات التشغيل من `.env`. المنفذ في المثال هو 8082، وقاعدة SQLite والصور المرفوعة بتتخزن في Docker volumes منفصلة عن الـcontainer.

## التشغيل باستخدام Compose

نفّذ الأوامر من مجلد المشروع. لو ملف `.env` مش موجود، أنشئه من المثال:

```bash
test -f .env || cp .env.example .env
```

اضبط `JWT_SECRET_KEY` في `.env` على قيمة عشوائية لا تقل عن 32 حرفًا. لتوليد قيمة:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

لو عندك مفتاح بالفعل في `.env`، احتفظ به. تغيير المفتاح يبطل التوكنات السابقة.

الإعدادات المهمة في `.env`:

| المتغير | القيمة في المثال | الاستخدام |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite+aiosqlite:///./blog.db` | قاعدة البيانات عند التشغيل المحلي خارج Docker. |
| `DOCKER_DATABASE_URL` | `sqlite+aiosqlite:////data/blog.db` | قاعدة البيانات داخل volume الخاص بـDocker. |
| `BLOG_PORT` | `8082` | المنفذ الذي تفتح عليه التطبيق من جهازك. |
| `JWT_SECRET_KEY` | مفتاحك الخاص | توقيع التوكنات والتحقق منها. |
| `JWT_ACCESS_TOKEN_MINUTES` | `30` | مدة صلاحية Access Token بالدقائق. |
| `REFRESH_TOKEN_DAYS` | `7` | مدة الجلسة بالأيام. |

ابدأ التشغيل:

```bash
docker compose config --quiet
docker compose up --build -d --wait
```

باستخدام `BLOG_PORT=8082`، التطبيق متاح على [localhost:8082](http://localhost:8082)، وتوثيق الـAPI على [localhost:8082/docs](http://localhost:8082/docs).

Compose بيحمّل `.env` من خلال `env_file`، وبيستبدل `DATABASE_URL` داخل الـcontainer بقيمة `DOCKER_DATABASE_URL`. إعدادات التطبيق بتتجاهل المتغيرات الإضافية الخاصة بـDocker، فملف `.env` نفسه يشتغل مع التشغيل المحلي أيضًا.

لتغيير المنفذ، عدّل `BLOG_PORT` في `.env` ثم أعد تشغيل الخدمة:

```bash
docker compose up -d --wait
```

المنفذ داخل الـcontainer ثابت على 8000. متغيرات الـshell لها الأولوية عند استخدام Compose لقيم مثل `BLOG_PORT` و`DOCKER_DATABASE_URL` و`JWT_SECRET_KEY` في إعداداته. لو غيّرت متغيرات التطبيق الأخرى في `.env`، نفّذ `docker compose up -d --force-recreate --wait` لضمان إعادة تحميلها.

## متابعة التشغيل وإيقافه

```bash
docker compose ps
docker compose logs -f web
docker compose down
```

`down` بيوقف ويحذف الـcontainer والشبكة الخاصة بالمشروع، مع الاحتفاظ بالـnamed volumes. إضافة `--volumes` إلى الأمر تحذف قاعدة البيانات والصور المخزنة في volumes المشروع. راجع [دورة حياة Docker volumes](https://docs.docker.com/engine/storage/volumes/#a-volumes-lifecycle).

بعد تعديل الكود أو المتطلبات، شغّل `docker compose up --build -d --wait` لإعادة البناء والتشغيل. الملفات مش مربوطة من جهازك داخل الـcontainer، وUvicorn بيشتغل من غير `--reload`.

## تخزين البيانات

| Volume في Compose | المسار داخل الـcontainer | المحتوى |
| --- | --- | --- |
| `blog_data` | `/data` | `blog.db` بما فيه الحسابات والبوستات وتوكنات التجديد والإلغاء. |
| `blog_media` | `/app/app/media` | الصور المرفوعة داخل `profile_pics`. |

Docker بيضيف اسم مشروع Compose إلى أسماء الـvolumes الفعلية. استخدام نفس اسم المشروع بيعيد استخدام نفس البيانات عند إعادة التشغيل أو إنشاء container جديد.

أول تشغيل بيبدأ بقاعدة بيانات وصور مستقلة عن الموجودين محليًا. ملف `blog.db` ومجلد `app/media` على جهازك لا يتم نسخهما إلى الصورة أو نقلهما تلقائيًا للـvolumes. الجداول الناقصة بتتعمل تلقائيًا عند بدء التطبيق.

## تشغيل Docker من غير Compose

باستخدام نفس ملف `.env` الذي يحتوي على مفتاح JWT:

```bash
docker build -t fastapi-blog:local .
docker run -d \
  --name fastapi-blog \
  --init \
  --env-file .env \
  --env DATABASE_URL=sqlite+aiosqlite:////data/blog.db \
  --publish 127.0.0.1:8082:8000 \
  --mount type=volume,source=fastapi-blog-data,target=/data \
  --mount type=volume,source=fastapi-blog-media,target=/app/app/media \
  fastapi-blog:local
```

`--env DATABASE_URL=...` بيحدد مسار قاعدة البيانات داخل الـvolume بدل المسار المحلي الموجود في `.env`. الـvolumes المسماة في المثال مستقلة عن volumes Compose؛ اختار طريقة التشغيل المناسبة واستخدم نفس أسماء الـvolumes للحفاظ على بياناتها.

للمتابعة والإيقاف:

```bash
docker logs -f fastapi-blog
docker stop fastapi-blog
docker rm fastapi-blog
```

## إعداد الصورة وفحص الحالة

التطبيق بيشتغل بمستخدم `blog` ورقم `10001`، وله صلاحية الكتابة في مسارات البيانات والصور. السيرفر بيستخدم Uvicorn بعملية worker واحدة، وبيسمع على `0.0.0.0:8000` داخل الـcontainer. ربط المنفذ في Compose بيتيح الوصول من الجهاز المحلي على `127.0.0.1`.

الـhealthcheck بيطلب `/api/posts/?per_page=1` كل 30 ثانية، وبالتالي بيتحقق من استجابة الـAPI ووصوله لقاعدة البيانات. له فترة بدء 20 ثانية وثلاث محاولات فاشلة قبل اعتبار الحالة `unhealthy`. حالة الفحص تظهر في `docker compose ps`. إعداد `restart: unless-stopped` يعيد تشغيل العملية لو خرجت، لكنه لا يعيد تشغيل container لمجرد تحوّل حالته إلى `unhealthy`؛ راجع [إعدادات خدمة Compose](https://docs.docker.com/reference/compose-file/services/).

ملف `.dockerignore` بيستبعد `.env` وقاعدة البيانات المحلية والصور المرفوعة و`.git` والـvirtual environment والاختبارات والتوثيق من build context. مفتاح JWT يُمرّر وقت التشغيل ولا يُضاف إلى صورة التطبيق.

شرح الدخول والتجديد والإلغاء موجود في [Authentication Flow الحالي](AUTHENTICATION_FLOW_AR.md).
