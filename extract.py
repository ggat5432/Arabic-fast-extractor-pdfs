import os
import re
import numpy as np
import easyocr
from pathlib import Path
from pdf2image import convert_from_path

# --- الإعدادات ---
FOLDER = "folder"
OUTPUT = "output"

# إعدادات التخطيط الذكي المحسنة (Smart Layout Settings)
Y_THRESHOLD = 20        # أقصى فرق عمودي لاعتبار الكلمات في نفس السطر (تمت زيادته ليتناسب مع الكلمات المتعرجة)
GAP_THRESHOLD = 40      # العتبة: إذا كان الفراغ بين كلمتين أكثر من 40 بكسل، نعتبره جدولة/أعمدة ونضيف مسافات
SPACE_WIDTH = 15        # عرض "المسافة" الواحدة بالبكسل للتعويض

# تحميل محرك EasyOCR 
reader = easyocr.Reader(['ar', 'en'], gpu=False)

def clean_text(text):
    """تنظيف النص المستخرج من الضجيج والرموز المكررة"""
    if not text: return ""
    text = re.sub(r'([1ا س -])\1{3,}', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def assemble_line(line_data):
    """ترتيب السطر من اليمين لليسار بناءً على الحواف الحقيقية للكلمات"""
    if not line_data:
        return ""
    
    # line_data تحتوي على: (max_x, min_x, text)
    # الترتيب بناءً على الحافة اليمنى (max_x) من الأكبر للأصغر (لأن العربية من اليمين لليسار)
    line_data.sort(key=lambda item: item[0], reverse=True)
    
    # أول كلمة من اليمين
    assembled_text = line_data[0][2]
    # نحتفظ بالحافة اليسرى للكلمة الحالية لنقارنها مع الكلمة التالية
    last_min_x = line_data[0][1] 
    
    # المرور على باقي الكلمات في السطر
    for max_x, min_x, text in line_data[1:]:
        # حساب الفجوة الحقيقية: الحافة اليسرى للكلمة السابقة - الحافة اليمنى للكلمة الحالية
        gap = last_min_x - max_x
        
        # إذا كانت الفجوة أكبر من المسافة الطبيعية بين كلمتين في جملة
        if gap > GAP_THRESHOLD: 
            spaces_count = int(gap / SPACE_WIDTH)
            assembled_text += (" " * spaces_count) + text
        else:
            # جملة طبيعية، نضع مسافة واحدة فقط
            assembled_text += " " + text
            
        # تحديث الحافة اليسرى للكلمة الحالية
        last_min_x = min_x
        
    return assembled_text.strip()

def process_with_layout(img_np):
    """استخراج النص مع الحفاظ على التخطيط عبر الإحداثيات الحقيقية"""
    result = reader.readtext(img_np, detail=1, paragraph=False)
    
    if not result:
        return ""

    boxes = []
    for bbox, text, prob in result:
        cleaned_word = clean_text(text)
        if not cleaned_word:
            continue
            
        # استخراج الإحداثيات الدقيقة للكلمة
        xs = [pt[0] for pt in bbox]
        ys = [pt[1] for pt in bbox]
        
        max_x = max(xs) # الحافة اليمنى
        min_x = min(xs) # الحافة اليسرى
        center_y = sum(ys) / 4.0 # مركز الكلمة عمودياً
        
        boxes.append((center_y, max_x, min_x, cleaned_word))

    # ترتيب عمودي للكلمات من أعلى الصفحة لأسفلها
    boxes.sort(key=lambda item: item[0])

    lines = []
    current_line = []
    if boxes:
        current_y = boxes[0][0]

    for center_y, max_x, min_x, text in boxes:
        # إذا نزلنا لسطر جديد
        if abs(center_y - current_y) > Y_THRESHOLD:
            lines.append(assemble_line(current_line))
            current_line = []
            current_y = center_y
        
        current_line.append((max_x, min_x, text))

    # السطر الأخير
    if current_line:
        lines.append(assemble_line(current_line))

    return "\n".join(lines)

def process_file(file_path):
    ext = file_path.suffix.lower()
    pages = []
    print(f"⚙️ جاري معالجة الملف (Smart Layout-Aware): {file_path.name}")
    
    if ext == ".pdf":
        images = convert_from_path(file_path, dpi=150) 
        for i, img in enumerate(images):
            print(f"📖 تحليل التخطيط للصفحة {i+1}...")
            img_np = np.array(img)
            page_text = process_with_layout(img_np)
            pages.append(page_text)
            del img_np
            
    elif ext in [".docx", ".txt"]:
        print(f"📄 قراءة محتوى نصي مباشر...")
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                pages.append(f.read())
        except UnicodeDecodeError:
            with open(file_path, "r", encoding="latin-1") as f:
                pages.append(f.read())
        
    return pages

def save_raw_text(pages, base_name):
    os.makedirs(OUTPUT, exist_ok=True)
    txt_path = Path(OUTPUT) / f"{base_name}.txt"
    
    separator = "\n\n--- صفحة جديدة ---\n\n"
    full_content = separator.join(pages)
    
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(full_content)
    
    print(f"✅ تم حفظ النص بالتنسيق الذكي والدقيق في: {txt_path}")

def main():
    os.makedirs(FOLDER, exist_ok=True)
    os.makedirs(OUTPUT, exist_ok=True)
    
    supported = [".pdf", ".docx", ".txt"]
    files = [f for f in Path(FOLDER).glob("*.*") if f.suffix.lower() in supported]
    
    if not files:
        print("❌ المجلد فارغ! يرجى وضع الملفات في مجلد folder")
        return
    
    latest = max(files, key=lambda x: x.stat().st_mtime)
    pages = process_file(latest)
    
    if pages:
        save_raw_text(pages, latest.stem)
        print(f"🚀 انتهت عملية الاستخراج الذكي بنجاح.")

if __name__ == "__main__":
    main()
