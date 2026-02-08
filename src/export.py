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


        #if the value is a list, split it into multiple columns like tester1, tester2, tester3. But dont touch the original data list, create a new one with the modified keys and values. This is because the original data list may be used elsewhere in the code and we don't want to modify it.
    modified_data = []
    for row in data:
        modified_row = {}
        for key, value in row.items():
            if isinstance(value, list):
                for i, item in enumerate(value):
                    modified_row[f"{key}{i+1}"] = item
            else:
                modified_row[key] = value
        modified_data.append(modified_row)
    
    data = modified_data


    with open(filename, mode='w', newline='', encoding='utf-8') as file:
        writer = csv.DictWriter(file, fieldnames=data[0].keys())
        writer.writeheader()
        writer.writerows(data)



    print(f"Data successfully exported to {filename}.")