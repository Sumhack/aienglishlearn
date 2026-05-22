
# import boto3
# from boto3.dynamodb.conditions import Key

# dynamodb = boto3.resource("dynamodb")
# table = dynamodb.Table("personas")

# image_updates = {
#     # "ceo": "corporate_priya.png",
#     # "cto": "corporate_kunal.png",
#     # "director_sales_marketing": "corporate_meera.png",
#     # "client": "corporate_client_thompson.png",
#     # "tech_lead": "corporate_aarav.png",
#     # "product_manager": "corporate_rajiv.png",
#     # "hr_interviewer": "interview_anjali.png",
#     # "technical_interviewer": "interview_karan.png",
#     # "hiring_manager": "interview_pooja.png",
#     # "investor": "founder_daniel.png",
#     # "enterprise_buyer": "founder_sophie.png",
#     # "b2c_user": "founder_rohan.png",
#     # "upsc_panelist": "exam_vivek.png",
#     # "mba_interviewer": "exam_radhika.png",
#     # "admissions_consultant": "exam_laura.png",
#     # "arjun_office_colleague": "social_arjun.png",
#     # "riya_new_friend": "social_riya.png",
#     "professor": "academia_ananya.png",
#     # "colleague": "academia_micheal.png",
#     # "department_chair": "academia_priya.png"
# }

# # Scan all existing records
# response = table.scan()
# items = response.get("Items", [])

# for item in items:
#     module_key = item.get("module_key")

#     if module_key in image_updates:
#         table.update_item(
#             Key={
#                 "coach_category": item["coach_category"],
#                 "module_key": module_key
#             },
#             UpdateExpression="SET image_name = :img",
#             ExpressionAttributeValues={
#                 ":img": image_updates[module_key]
#             },
#             ConditionExpression="attribute_exists(coach_category)"
#         )

#         print(f"Updated {module_key}")

# print("All image_name fields updated.")

import boto3

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table("sessions")

# Mapping: coach_type -> coach_category
coach_category_mapping = {
    "CEO": "Corporate",
    "CTO": "Corporate",
    "Director Sales & Marketing": "Corporate",
    "Client": "Corporate",
    "Tech Lead": "Corporate",
    "Product Manager": "Corporate",

    "HR Interviewer": "Job Interviews",
    "Technical Interviewer": "Job Interviews",
    "Hiring Manager": "Job Interviews",

    "Investor": "Founders",
    "Enterprise Buyer": "Founders",
    "B2C User": "Founders",

    "Professor": "Academics",
    "Colleague": "Academics",
    "Department Chair": "Academics",

    "UPSC Panelist": "Competitive Exams",
    "MBA Interviewer": "Competitive Exams",
    "Admissions Consultant": "Competitive Exams",

    "Office Colleague": "Social Conversations",
    "New Friend": "Social Conversations"
}

# Scan all sessions
response = table.scan()
items = response.get("Items", [])

while "LastEvaluatedKey" in response:
    response = table.scan(
        ExclusiveStartKey=response["LastEvaluatedKey"]
    )
    items.extend(response.get("Items", []))

print(f"Found {len(items)} sessions")

for item in items:
    coach_type = item.get("coach_type")

    if coach_type in coach_category_mapping:
        coach_category = coach_category_mapping[coach_type]

        table.update_item(
            Key={
                "session_id": item["session_id"]
            },
            UpdateExpression="SET coach_category = :category",
            ExpressionAttributeValues={
                ":category": coach_category
            },
            ConditionExpression="attribute_exists(session_id)"
        )

        print(f"Updated session {item['session_id']} -> {coach_category}")

print("All coach_category fields updated successfully.")