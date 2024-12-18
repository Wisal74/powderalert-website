import streamlit as st
import requests
from datetime import datetime, timedelta
import pytz
import plotly.express as px
import pandas as pd
from retry_requests import retry
import openmeteo_requests
import requests_cache

# Constants
HOCHFUEGEN_TZ = pytz.timezone("Europe/Vienna")
WEBCAM_URL = "https://sts210.feratel.co.at/streams/stsstore203/1/05560_6762951a-cbf7Vid.mp4?dcsdesign=WTP_bergfex.at"
# Dark blue theme colors
DARK_BLUE = 'rgba(25, 25, 112, 0.5)'  # Dark blue with 0.9 opacity
LIGHT_TEXT = '#FFFFFF'  # White text for contrast
GRID_COLOR = 'rgba(255, 255, 255, 0.2)'  # Subtle white grid
CHART_CONFIG = {
    'background_color': DARK_BLUE,
    'font_color': LIGHT_TEXT,
    'grid_color': GRID_COLOR
}

# Helper function to generate next 48-hour dropdown options
def generate_time_options():
    now = datetime.now(HOCHFUEGEN_TZ)
    options = [(now + timedelta(hours=i)).strftime("%Y-%m-%d %H:00") for i in range(48)]
    return options

# Setup the Open-Meteo API client with cache and retry on error
cache_session = requests_cache.CachedSession('.cache', expire_after = -1)
retry_session = retry(cache_session, retries = 5, backoff_factor = 0.2)
openmeteo = openmeteo_requests.Client(session = retry_session)

# Make sure all required weather variables are listed here
# The order of variables in hourly or daily is important to assign them correctly below
url = "https://api.open-meteo.com/v1/forecast"
params = {
    "latitude": 47.26580883196723,
    "longitude": 11.84457426992035,
    'past_days': 7,
    'forecast_days': 0,
    "hourly": ["temperature_2m", "relative_humidity_2m", "dew_point_2m", "precipitation", "rain", "snowfall", "snow_depth", "weather_code", "pressure_msl", "surface_pressure", "cloud_cover", "cloud_cover_low", "cloud_cover_mid", "cloud_cover_high", "et0_fao_evapotranspiration", "vapour_pressure_deficit", "wind_speed_10m", "wind_speed_120m", "wind_direction_10m", "wind_direction_120m", "wind_gusts_10m", "soil_temperature_0cm", "soil_temperature_6cm", "soil_temperature_18cm", "soil_temperature_54cm", "soil_moisture_0_to_1cm", "soil_moisture_1_to_3cm", "soil_moisture_3_to_9cm", "soil_moisture_9_to_27cm", "soil_moisture_27_to_81cm"]
}
responses = openmeteo.weather_api(url, params=params)

# Process first location. Add a for-loop for multiple locations or weather models
response = responses[0]
# Process hourly data. The order of variables needs to be the same as requested.
hourly = response.Hourly()
hourly_temperature = hourly.Variables(0).ValuesAsNumpy()
hourly_snow_depth = hourly.Variables(6).ValuesAsNumpy()

hourly_data = {"date": pd.date_range(
	start = pd.to_datetime(hourly.Time(), unit = "s", utc = True),
	end = pd.to_datetime(hourly.TimeEnd(), unit = "s", utc = True),
	freq = pd.Timedelta(seconds = hourly.Interval()),
	inclusive = "left"
)}

hourly_data["snow_depth"] = hourly_snow_depth * 100
hourly_data["temperature"] =hourly_temperature
hourly_dataframe = pd.DataFrame(data = hourly_data)
def create_forecast_chart(data):
    # Melt the data to create a "long format" for multiple y-series
    data_long = data.melt(id_vars='date',
                          value_vars=['snow_depth', 'temperature'],
                          var_name='variable',
                          value_name='value')

    # Create the line chart
    fig = px.line(
        data_long,
        x='date',
        y='value',
        color='variable',  # Different colors for Snow Depth and Temperature
        title="7-Day Snow Depth and Temperature Forecast",
        labels={'value': 'Measurement', 'variable': 'Legend'},
    )

    # Update layout for styling
    fig.update_layout(
        xaxis_title="Date",
        yaxis_title="Measurement",
        template="plotly_white",
        paper_bgcolor=CHART_CONFIG['background_color'],
        plot_bgcolor=CHART_CONFIG['background_color'],
        font_color=CHART_CONFIG['font_color'],
        xaxis=dict(
            gridcolor=CHART_CONFIG['grid_color'],
            showgrid=True
        ),
        yaxis=dict(
            gridcolor=CHART_CONFIG['grid_color'],
            showgrid=True
        )
    )

    return fig


# Title and subheader
st.title("Hochfügen Ski Resort Forecast")
st.markdown("### Get accurate snowfall and temperature forecasts for the next 48 hours.")

# Webcam
st.markdown("#### Hochfügen Lamarkalm Webcam")
st.markdown(
    f'<iframe src="{WEBCAM_URL}" width="100%" height="400" style="border:0;"></iframe>',
    unsafe_allow_html=True,
)

st.markdown("#### Snowfall Forecast")
snowfall_placeholder = st.empty()
st.markdown("#### Temperature Forecast")
temperature_placeholder = st.empty()

# Dropdown for time selection
st.header("Choose Forecast Time")
time_options = generate_time_options()
selected_time = st.selectbox("Select Date and Time:", time_options)

# Forecast button
if st.button("Get Forecast"):
    # Extract date and hour from selected time
    selected_date, selected_hour = selected_time.split(" ")

    # Placeholder API endpoints
    snowfall_api_url = "https://powderalert-884569188278.europe-west1.run.app/predict_snowfall?lat=47.26580883196723&long=11.84457426992035"
    temperature_api_url = "https://powderalert-884569188278.europe-west1.run.app/predict_temperature?lat=47.26580883196723&long=11.84457426992035"

    # Snowfall API request
    try:
        snowfall_response = requests.post(
            snowfall_api_url, json={"date": selected_date, "hour": selected_hour}
        )
        if snowfall_response.status_code == 200:
            snowfall_data = snowfall_response.json()
            first_predict_time = snowfall_data.get("first_predict_time")
            snowfall_predictions = snowfall_data.get("snowfall_prediction", [])

            # Display snowfall predictions
            snowfall_placeholder.metric(
                label="Predicted Snowfall (cm)",
                value=f"{snowfall_predictions[0]:.2f}" if snowfall_predictions else "N/A",
                delta=f"First prediction at {first_predict_time}" if first_predict_time else "N/A"
            )
        else:
            snowfall_placeholder.error("Error retrieving snowfall data.")
    except Exception as e:
        snowfall_placeholder.error(f"Error: {e}")

    # Temperature API request
    try:
        temperature_response = requests.post(
            temperature_api_url, json={"date": selected_date, "hour": selected_hour}
        )
        if temperature_response.status_code == 200:
            temperature_data = temperature_response.json()
            temperature_predictions = temperature_data.get("temperature_prediction", [])

            # Display temperature predictions
            temperature_placeholder.metric(
                label="Predicted Temperature (°C)",
                value=f"{temperature_predictions[0]:.2f}" if temperature_predictions else "N/A"
            )
        else:
            temperature_placeholder.error("Error retrieving temperature data.")
    except Exception as e:
        temperature_placeholder.error(f"Error: {e}")

# Display forecast chart
    st.plotly_chart(
        create_forecast_chart(hourly_dataframe),
        use_container_width=True
    )

# Styling for the wintery blue theme
st.markdown(
    """
    <style>
    .stApp {
        background: #373737;
        color: #81CBC7;
    }
    .stMetricLabel {
        font-size: 1.2rem;
        font-weight: bold;
    }
    iframe {
        border-radius: 16px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)
#https://powderalert-884569188278.europe-west1.run.app/predict_snowfall?lat=47.26580883196723&long=11.84457426992035
#https://powderalert-884569188278.europe-west1.run.app/predict_temperature?lat=47.26580883196723&long=11.84457426992035
