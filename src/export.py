import csv

def export_to_csv(data, filename):
    """
    Exports a list of dictionaries to a CSV file.

    :param data: List of dictionaries containing the data to export.
    :param filename: The name of the file to save the CSV data to.
    """
    if not data:
        print("No data to export.")
        return

    data = split_testers(data)


    with open(filename, mode='w', newline='', encoding='utf-8') as file:
        writer = csv.DictWriter(file, fieldnames=data[0].keys())
        writer.writeheader()
        writer.writerows(data)



    print(f"Data successfully exported to {filename}.")

def split_testers(data):
    modified_data = []
    for row in data:
        modified_row = {}
        for key, value in row.items():
            if key == "testers" and isinstance(value, list):
                for i, item in enumerate(value):
                    modified_row[f"{key}{i+1}"] = item
            else:
                modified_row[key] = value
        modified_data.append(modified_row)
    
    data = modified_data
    return data