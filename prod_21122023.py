import flask
import pandas as pd
import pygsheets
from google.cloud import bigquery
from google.cloud import secretmanager


# ------ CONFIG -----------------
# GCP
PROJECT_ID = 'stayloom'
# Secret Manager
SM_SECRET_NAME = 'sa-key-pricing-pipeline'
# BigQuery
BQ_DATASET_STAYLOOM = "guesty"
BQ_TABLE_EXPECTATIONS = "t_expectations"
# Google Sheets:
#   Heirloom Pricing Model
#   https://docs.google.com/spreadsheets/d/1cD6YngYtcGiy8zdqk80HwVE-ehHh5aAgBHFHVnhG3tI
SHEET_TITLE_HEIRLOOM_PRICING_MODEL = 'Heirloom Pricing Model'
SHEET_KEY_HEIRLOOM_PRICING_MODEL   = "1cD6YngYtcGiy8zdqk80HwVE-ehHh5aAgBHFHVnhG3tI"
SHEET_TAB_SEASONALITY              = 'Seasonality'
#   Sheet Title
#   https://docs.google.com/spreadsheets/d/1EnNxgP7zBd1tuTGikbWeLyx115npeFdxHnABW9hU8P0
SHEET_KEY   = '1EnNxgP7zBd1tuTGikbWeLyx115npeFdxHnABW9hU8P0'
# SHEET_TITLE = ''
SHEET_TAB   = 'Sheet1'


# ------ START ------------------
def get_expectations():
    # Fetch the SA key from Secret Manager
    sm = SecretManager(PROJECT_ID)
    sa_key_json = sm.get_secret(SM_SECRET_NAME)
    
    # Authenticate to G.Sheets
    gc = pygsheets.authorize(service_account_json=sa_key_json)

    # Expectation spread sheet
    dictionary = gc.open_by_key(SHEET_KEY)
    Worksheet_dictionary = dictionary.worksheet_by_title(SHEET_TAB)
    Df_Expectations = Worksheet_dictionary.get_as_df()
    Df_Expectations = Df_Expectations[Df_Expectations['Market'] != ""]
    Df_Expectations = Df_Expectations[
        ['Market', 'Unit Size', 'Month', 'Final Occupancy', 'Weeks Out', 'Expected Attainment(%)', 'Sd.',
         'Occup. Factor', 'Occupancy Sd.', 'ExpectedOccupancy', 'Upper  Occupancy', 'Lower Occupancy', 'Expected Weekend Occupancy']]
    Df_Expectations.columns = ['Market', 'Unit_Size', 'Month', 'Final_Occupancy', 'Weeks_Out',
                               'Expected_Attainment', 'Attain_Sd', 'Occup_Factor', 'Occupancy_Sd.',
                               'Expected_Occupancy', 'Upper_Occupancy', 'Lower_Occupancy', 'Expected_Weekend_Occupancy']

    # Seasonality spread sheet
    pricing_model = gc.open_by_key(SHEET_KEY_HEIRLOOM_PRICING_MODEL)
    Worksheet_seasonality = pricing_model.worksheet_by_title(SHEET_TAB_SEASONALITY)
    Df_seasonality = Worksheet_seasonality.get_as_df()
    Df_seasonality = Df_seasonality[Df_seasonality['City'] != ""]
    Df_seasonality = Df_seasonality[['City', 'Week', 'Factor', 'Month']]
    Df_seasonality.columns = ['Market', 'Week', 'Season_Factor', 'Month']

    # Filter the cells where valus is #VALUE!
    condition = Df_seasonality['Season_Factor'] == '#VALUE!'
    Df_seasonality = Df_seasonality.drop(Df_seasonality[condition].index)

    # Convert the season factor to float
    #   e.g. 100% -> 1.0
    Df_seasonality['Season_Factor'] = (Df_seasonality['Season_Factor'].replace('%', '', regex=True).astype(float)) / 100
    seasonality = Df_seasonality.groupby(['Market', 'Month']).mean().reset_index()

    Df_Expectations['Month'] = Df_Expectations['Month'].astype(str)
    seasonality['Month'] = seasonality['Month'].astype(str)
    final = pd.merge(Df_Expectations, seasonality, on=['Market', 'Month'], how='left')

    final.columns = ['market', 'unit_size', 'month', 'final_occupancy', 'weeks_out', 'expected_attainment', 'attain_sd',
                     'occup_factor', 'occupancy_sd', 'expected_occupancy', 'upper_occupancy', 'lower_occupancy', 'week',
                     'season_factor', 'Expected_Weekend_Occupancy']

    insert(final)


#
# def delete_data():
#     client = bigquery.Client.from_service_account_json(SERVICE_ACCOUNT_FILE)
#     query = f"""Delete from `{PROJECT_ID}.{BQ_DATASET_STAYLOOM}.{BQ_TABLE_EXPECTATIONS}` where 1=1 """
#     client.query(query)
#     print("delete data from expectation table")


def insert(df):
    # Create a job config
    client = bigquery.Client(PROJECT_ID)
    job_config = bigquery.LoadJobConfig()
    # Set the destination table
    table_ref = client.dataset(BQ_DATASET_STAYLOOM).table(BQ_TABLE_EXPECTATIONS)
    # time_partitioning = bigquery.table.TimePartitioning(field="date", require_partition_filter=True)

    job_config.write_disposition = 'WRITE_TRUNCATE'
    # job_config.time_partitioning = time_partitioning
    load_job = client.load_table_from_dataframe(df, table_ref, job_config=job_config)
    result = load_job.result()
    if result.errors is not None:
        print("Error occurred while inserting expectations data into bigquery " + str(result.errors))
    else:
        print("Expectations are inserted into bigquery successfully")


# ------ SECRET MANAGER ---------
class SecretManager():
    """ Construct Secret Manager client
    """
    client = secretmanager.SecretManagerServiceClient()

    def __init__(self, project_id):
        self.project_id = project_id
        self.parent = f"projects/{project_id}"

    def get_secret(self, secret_id, version_id:str = "latest"):
        """ Get secret value

            TODO:
                - Raise if secret not found
            Args:
                secret_id (str): Secret ID
                version_id (str): Secret version ID
                    default: latest
            Returns:
                secret_value (str): Secret value
        """
        # Access the secret version
        response = self.client.access_secret_version(
            request={
                "name": f"projects/{self.project_id}/secrets/{secret_id}/versions/{version_id}"
                })
        print("Accessed secret version: {}".format(response.name))
        # Return the decoded payload
        return response.payload.data.decode("UTF-8")   
    

# ------ ENTRY POINT ---------
def main():
    get_expectations()
    return flask.Response(status=200)


# # ------ TEST ----------------
# if __name__ == '__main__':
# 	main(request=None)
main()