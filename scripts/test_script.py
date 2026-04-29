import boto3
from boto3.dynamodb.conditions import Key, Attr
from decimal import Decimal

TABLE_NAME = "sessions"
INDEX_NAME = "user_id_index"

USER_ID = "759d9be0-150a-4a33-8027-cb97809f745f"
TARGET_SESSION_ID = "79d49aec-4872-4485-9afa-e3c9d4b3633a"


def run_debug():
    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(TABLE_NAME)

    last_evaluated_key = None
    page = 1

    found_without_filter = False
    found_with_filter = False

    total_items = 0
    total_filtered_items = 0

    print("\n🔍 Starting full pagination scan...\n")

    while True:
        query_kwargs = {
            "IndexName": INDEX_NAME,
            "KeyConditionExpression": Key("user_id").eq(USER_ID),
            "ScanIndexForward": False,
        }

        if last_evaluated_key:
            query_kwargs["ExclusiveStartKey"] = last_evaluated_key

        response = table.query(**query_kwargs)

        items = response.get("Items", [])
        print(f"\n📄 Page {page} — items fetched: {len(items)}")

        for item in items:
            total_items += 1

            sid = item.get("session_id")
            relevance = item.get("relevance_score")

            # Check without filter
            if sid == TARGET_SESSION_ID:
                found_without_filter = True
                print(f"\n✅ FOUND TARGET (without filter) on page {page}")
                print(f"   relevance_score = {relevance} (type={type(relevance)})")
                print(f"   created_at = {item.get('created_at')}")

            # Apply same filter as your code
            if relevance is not None and Decimal(relevance) > Decimal(0):
                total_filtered_items += 1

                if sid == TARGET_SESSION_ID:
                    found_with_filter = True
                    print(f"\n🔥 FOUND TARGET (WITH filter) on page {page}")

        last_evaluated_key = response.get("LastEvaluatedKey")

        if last_evaluated_key:
            print(f"➡️ More pages exist, continuing...\n")
            page += 1
        else:
            print("\n✅ No more pages.")
            break

    print("\n📊 SUMMARY")
    print(f"Total items scanned: {total_items}")
    print(f"Total items after filter: {total_filtered_items}")
    print(f"Found target without filter: {found_without_filter}")
    print(f"Found target with filter: {found_with_filter}")


# if __name__ == "__main__":
run_debug()