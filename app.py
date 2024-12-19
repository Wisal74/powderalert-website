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
WEBCAM_URL = "https://sts101.feratel.co.at/streams/stsstore105/1/05561_6762e97b-42c4Vid.mp4?dcsdesign=WTP_bergfex.at"

# Dark blue theme colors
DARK_BLUE = 'rgba(129, 203, 199, 0.5)'  # Dark blue with 0.9 opacity
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
    options = [(now + timedelta(hours=i)).strftime("%d-%m-%Y %H:00") for i in range(48)]
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

hourly_data["Snow Depth"] = hourly_snow_depth * 100
hourly_data["Temperature"] =hourly_temperature
hourly_dataframe = pd.DataFrame(data = hourly_data)

def fetch_combined_data(snowfall_url, temperature_url):
    try:
        # Fetch snowfall data
        snowfall_response = requests.get(snowfall_url)
        if snowfall_response.status_code == 200:
            snowfall_data = snowfall_response.json()
            snowfall_first_predict_time = datetime.strptime(snowfall_data["first_predict_time"], "%Y-%m-%dT%H:%M")
            snowfall_predictions = snowfall_data["snowfall_prediction"]
            snowfall_dates = [snowfall_first_predict_time + timedelta(hours=i) for i in range(len(snowfall_predictions))]
        else:
            print(f"Error: Snowfall API returned status code {snowfall_response.status_code}")
            return None

        # Fetch temperature data
        temperature_response = requests.get(temperature_url)
        if temperature_response.status_code == 200:
            temperature_data = temperature_response.json()
            temperature_first_predict_time = datetime.strptime(temperature_data["first_predict_time"], "%Y-%m-%dT%H:%M")
            temperature_predictions = temperature_data["temperature_prediction"]
            temperature_dates = [temperature_first_predict_time + timedelta(hours=i) for i in range(len(temperature_predictions))]
        else:
            print(f"Error: Temperature API returned status code {temperature_response.status_code}")
            return None

        # Ensure data alignment and combine into a single DataFrame
        if snowfall_dates == temperature_dates:
            combined_df = pd.DataFrame({
                "date": snowfall_dates,
                "Snowfall": snowfall_predictions,
                "Temperature": temperature_predictions
            })
            return combined_df
        else:
            print("Error: Dates from Snowfall and Temperature predictions do not match.")
            return None

    except Exception as e:
        print(f"Error: API request failed with exception: {e}")
        return None

def create_forecast_chart(data, value_vars):
    # Melt the data to create a "long format" for multiple y-series
    data_long = data.melt(id_vars='date',
                          value_vars=value_vars,
                          var_name='variable',
                          value_name='value')

    # Create the line chart
    fig = px.line(
        data_long,
        x='date',
        y='value',
        color='variable',  # Different colors for Snow Depth and Temperature
        labels={'value': 'Measurement', 'variable': 'legend'},
    )

    # Update layout for styling
    fig.update_layout(
        xaxis_title=None,
        yaxis_title=None,
        template="plotly_white",
        paper_bgcolor='#373737',
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
st.markdown("##### Get accurate snowfall and temperature forecasts for the next 48 hours.")
st.markdown("##### ")

# Webcam
st.markdown("### Hochfügen Lamarkalm Webcam")
st.markdown(
    f'<iframe src="{WEBCAM_URL}" width="100%" height="400" style="border:0;"></iframe>',
    unsafe_allow_html=True,
)
st.markdown("##### ")

# Dropdown for time selection
st.markdown("### Choose Forecast Time")
time_options = generate_time_options()
selected_time = st.selectbox("Select Date and Time:", time_options, label_visibility='collapsed')

# Forecast button
if st.button("Get Forecast"):
    st.markdown("##### ")
    # Extract date and hour from selected time
    selected_date, selected_hour = selected_time.split(" ")

    # Placeholder API endpoints
    snowfall_api_url = "https://powderalert-884569188278.europe-west1.run.app/predict_snowfall?lat=47.26580883196723&long=11.84457426992035"
    temperature_api_url = "https://powderalert-884569188278.europe-west1.run.app/predict_temperature?lat=47.26580883196723&long=11.84457426992035"

    col1, col2 = st.columns([1, 1])
    with col1:
    # Snowfall API request
        try:
            snowfall_response = requests.get(snowfall_api_url)
            if snowfall_response.status_code == 200:
                snowfall_data = snowfall_response.json()
                #first_predict_time = snowfall_data.get("first_predict_time")
                snowfall_predictions = snowfall_data.get("snowfall_prediction", [])

                # Display snowfall predictions
                st.markdown("#### Snowfall Forecast")
                snowfall_placeholder = st.metric(
                    label="Predicted Snowfall (cm)",
                    value=f"{snowfall_predictions[0]:.2f} cm" if snowfall_predictions else "N/A",
                    label_visibility='collapsed'
                    #delta=f"First prediction at {first_predict_time}" if first_predict_time else "N/A"
                )
            else:
                "Error retrieving snowfall data."
        except Exception as e:
            f"Error: {e}"
    with col2:
        # Temperature API request
        try:
            temperature_response = requests.get(temperature_api_url)
            if temperature_response.status_code == 200:
                temperature_data = temperature_response.json()
                temperature_predictions = temperature_data.get("temperature_prediction", [])

                # Display temperature predictions
                st.markdown("#### Temperature Forecast")
                temperature_placeholder = st.metric(
                    label="Predicted Temperature (°C)",
                    label_visibility='collapsed',
                    value=f"{round(temperature_predictions[0])} °C" if temperature_predictions else "N/A"
                )
            else:
                "Error retrieving temperature data."
        except Exception as e:
            f"Error: {e}"

    # Fetch the combined data
    combined_df = fetch_combined_data(snowfall_api_url, temperature_api_url)

   # Display forecast chart
    st.markdown("##### ")
    st.markdown("### Next 48 hours snowfall (cm) and temperature (°C) forecast")
    st.plotly_chart(
        create_forecast_chart(combined_df, value_vars=["Snowfall", "Temperature"]),
        use_container_width=True
        )

# Display forecast chart
st.markdown("##### ")
st.markdown("### Previous 7 days snow depth (cm) and temperature (°C)")
st.plotly_chart(
    create_forecast_chart(hourly_dataframe, value_vars=['Snow Depth', 'Temperature']),
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
        border-radius: 16px; /* Rounded corners for iframe */
    }
    /* Custom selectbox size */
    div[data-baseweb="select"] {
        width: 200px !important;
    }
    /* Selected value area */
    div[data-baseweb="select"] > div {
        background-color: #373737 !important; /* Background color */
        color: #81CBC7 !important; /* Font color */
        border: 1px solid #81CBC7 !important; /* Border color */
        border-radius: 8px !important; /* Rounded corners */
        font-weight: normal;
    }
    /* Dropdown list (menu) */
    ul[role="listbox"] {
        background-color: #2E3B4E !important; /* Background color for dropdown */
        border: 2px solid #F5AF80 !important; /* Border color for dropdown */
    }
    /* Dropdown list items */
    ul[role="listbox"] > li {
        background-color: #373737 !important; /* Item background */
        color: #81CBC7 !important; /* Item font color */
        font-weight: bold;
        padding: 8px;
    }
    /* Hover effect for dropdown items */
    ul[role="listbox"] > li:hover {
        background-color: #81CBC7 !important; /* Hover background */
        color: #373737 !important; /* Hover text color */
    }
    /* Selected dropdown option */
    ul[role="listbox"] > li[aria-selected="true"] {
        background-color: #81CBC7 !important; /* Selected background color */
        color: #373737 !important; /* Selected font color */
    }
    /* Customize button */
    div.stButton > button {
        background-color: #373737 !important; /* Button background color */
        color: #81CBC7 !important; /* Button text color */
        border-radius: 8px; /* Rounded corners for the button */
        border-color: #81CBC7; /* Remove button border */
        font-weight: bold;
        font-size: 16px;
    }
        /* Button hover effect */
    div.stButton > button:hover {
        background-color: #81CBC7 !important; /* Background color on hover */
        color: #373737 !important; /* Text color on hover */
        border: 2px solid #81CBC7 !important; /* Border color on hover */
    }
    </style>
    """,
    unsafe_allow_html=True,
)
