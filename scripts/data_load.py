```python
import boto3
from boto3.dynamodb.conditions import Key

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table("personas")

image_updates = {
    "ceo": "corporate_priya.png",
    "cto": "corporate_kunal.png",
    "director_sales_marketing": "corporate_meera.png",
    "client": "corporate_client_thompson.png",
    "tech_lead": "corporate_aarav.png",
    "product_manager": "corporate_rajiv.png",
    "hr_interviewer": "interview_anjali.png",
    "technical_interviewer": "interview_karan.png",
    "hiring_manager": "interview_pooja.png",
    "investor": "founder_daniel.png",
    "enterprise_buyer": "founder_sophie.png",
    "b2c_user": "founder_rohan.png",
    "upsc_panelist": "exam_vivek.png",
    "mba_interviewer": "exam_radhika.png",
    "admissions_consultant": "exam_laura.png",
    "arjun_office_colleague": "social_arjun.png",
    "riya_new_friend": "social_riya.png",
    "professor": "academia_priya.png",
    "colleague": "academia_micheal.png",
    "department_chair": "academia_priya.png"
}

# Scan all existing records
response = table.scan()
items = response.get("Items", [])

for item in items:
    module_key = item.get("module_key")

    if module_key in image_updates:
        table.update_item(
            Key={
                "coach_category": item["coach_category"],
                "module_key": module_key
            },
            UpdateExpression="SET image_name = :img",
            ExpressionAttributeValues={
                ":img": image_updates[module_key]
            },
            ConditionExpression="attribute_exists(coach_category)"
        )

        print(f"Updated {module_key}")

print("All image_name fields updated.")