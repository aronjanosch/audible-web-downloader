"""
Custom exception classes and error handling utilities.
Provides standardized error responses for the application.
"""
from typing import Optional, Dict, Any
from flask import jsonify


class AppError(Exception):
    """Base exception for all application errors."""
    
    def __init__(self, message: str, code: str = "APP_ERROR", details: Optional[Dict] = None, status_code: int = 500):
        self.message = message
        self.code = code
        self.details = details or {}
        self.status_code = status_code
        super().__init__(self.message)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to dictionary for JSON responses."""
        return {
            "success": False,
            "error": {
                "message": self.message,
                "code": self.code,
                "details": self.details
            }
        }
    
    def to_response(self):
        """Convert exception to Flask JSON response."""
        return jsonify(self.to_dict()), self.status_code


class NotFoundError(AppError):
    """Resource not found error."""
    
    def __init__(self, resource_type: str, identifier: Optional[str] = None, details: Optional[Dict] = None):
        message = f"{resource_type} not found"
        if identifier:
            message += f": {identifier}"
        code = f"{resource_type.upper().replace(' ', '_')}_NOT_FOUND"
        super().__init__(message, code, details, 404)


class AccountNotFoundError(NotFoundError):
    """Account not found error."""
    
    def __init__(self, account_name: str):
        super().__init__("Account", account_name)


class LibraryNotFoundError(NotFoundError):
    """Library not found error."""
    
    def __init__(self, library_name: str):
        super().__init__("Library", library_name)


class ValidationError(AppError):
    """Input validation error."""
    
    def __init__(self, message: str, field: Optional[str] = None, details: Optional[Dict] = None):
        error_details = details or {}
        if field:
            error_details['field'] = field
        super().__init__(message, "VALIDATION_ERROR", error_details, 400)


class AuthenticationError(AppError):
    """Authentication error."""
    
    def __init__(self, message: str = "Authentication required", details: Optional[Dict] = None):
        super().__init__(message, "AUTHENTICATION_ERROR", details, 401)


class AuthorizationError(AppError):
    """Authorization error."""
    
    def __init__(self, message: str = "Permission denied", details: Optional[Dict] = None):
        super().__init__(message, "AUTHORIZATION_ERROR", details, 403)


class ConfigurationError(AppError):
    """Configuration error."""
    
    def __init__(self, message: str, details: Optional[Dict] = None):
        super().__init__(message, "CONFIGURATION_ERROR", details, 500)


class DownloadError(AppError):
    """Download operation error."""
    
    def __init__(self, message: str, asin: Optional[str] = None, details: Optional[Dict] = None):
        error_details = details or {}
        if asin:
            error_details['asin'] = asin
        super().__init__(message, "DOWNLOAD_ERROR", error_details, 500)


class ImportError(AppError):
    """Import operation error."""
    
    def __init__(self, message: str, file_path: Optional[str] = None, details: Optional[Dict] = None):
        error_details = details or {}
        if file_path:
            error_details['file_path'] = file_path
        super().__init__(message, "IMPORT_ERROR", error_details, 500)


def error_response(message: str, code: str = "ERROR", status_code: int = 500, details: Optional[Dict] = None):
    """
    Create a standardized error response.
    
    Args:
        message: Error message
        code: Error code (e.g., "ACCOUNT_NOT_FOUND")
        status_code: HTTP status code
        details: Additional error details
    
    Returns:
        Tuple of (jsonify response, status_code)
    """
    return jsonify({
        "success": False,
        "error": {
            "message": message,
            "code": code,
            "details": details or {}
        }
    }), status_code


def success_response(data: Optional[Dict] = None, message: Optional[str] = None, status_code: int = 200):
    """
    Create a standardized success response.
    
    Args:
        data: Response data
        message: Optional success message
        status_code: HTTP status code
    
    Returns:
        Tuple of (jsonify response, status_code)
    """
    response = {
        "success": True
    }
    
    if message:
        response['message'] = message
    
    if data:
        response.update(data)
    
    return jsonify(response), status_code


def register_error_handlers(app):
    """
    Register Flask error handlers for custom exceptions.
    
    Args:
        app: Flask application instance
    """
    
    @app.errorhandler(AppError)
    def handle_app_error(error):
        """Handle all custom application errors."""
        return error.to_response()
    
    @app.errorhandler(404)
    def handle_404(error):
        """Handle 404 Not Found errors."""
        return error_response(
            message="The requested resource was not found",
            code="NOT_FOUND",
            status_code=404
        )
    
    @app.errorhandler(500)
    def handle_500(error):
        """Handle 500 Internal Server Error."""
        return error_response(
            message="An internal server error occurred",
            code="INTERNAL_SERVER_ERROR",
            status_code=500
        )

