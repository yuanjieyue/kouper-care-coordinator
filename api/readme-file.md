# Basic Flask API

A simple Flask application that serves JSON data through a REST API endpoint.

## Prerequisites

- Python 3.7 or higher
- pip (Python package installer)

## Setup Instructions

1. Create a virtual environment (recommended):
```bash
python -m venv venv
```

2. Activate the virtual environment:
- On Windows:
```bash
venv\Scripts\activate
```
- On macOS/Linux:
```bash
source venv/bin/activate
```

3. Install required packages:
```bash
pip install flask
```

## Running the Application

1. Make sure your virtual environment is activated

2. Run the Flask application:
```bash
python app.py
```

3. The server will start on `http://localhost:5000`

## Testing the API

You can test the API endpoint using curl or your web browser:

```bash
curl http://localhost:5000/patient/{id}
```

Or simply visit `http://localhost:5000/patient/{id}` in your web browser.

## API Endpoints

- `GET /patient/{id}`: Returns a JSON about the patient