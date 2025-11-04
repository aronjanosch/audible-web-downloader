"""
Input validation schemas using Pydantic.
Provides type-safe validation for API endpoints.
"""
from typing import List, Optional, Dict, Any, Callable
from pydantic import BaseModel, Field, validator, field_validator, ValidationError
from pathlib import Path
from functools import wraps
from flask import request
from utils.errors import ValidationError as AppValidationError


# ========== Account Management ==========

class CreateAccountRequest(BaseModel):
    """Schema for creating a new account"""
    account_name: str = Field(..., min_length=1, max_length=100, description="Account name")
    region: str = Field(default="us", pattern="^[a-z]{2}$", description="Two-letter region code")
    
    @field_validator('account_name')
    @classmethod
    def validate_account_name(cls, v):
        # Remove leading/trailing whitespace
        v = v.strip()
        if not v:
            raise ValueError('Account name cannot be empty')
        # Check for invalid characters
        invalid_chars = ['/', '\\', ':', '*', '?', '"', '<', '>', '|']
        if any(char in v for char in invalid_chars):
            raise ValueError(f'Account name contains invalid characters: {", ".join(invalid_chars)}')
        return v


class SelectAccountRequest(BaseModel):
    """Schema for selecting an account"""
    account_name: str = Field(..., min_length=1)


# ========== Library Management ==========

class CreateLibraryRequest(BaseModel):
    """Schema for creating a new library"""
    library_name: str = Field(..., min_length=1, max_length=100)
    library_path: str = Field(..., min_length=1)
    
    @field_validator('library_path')
    @classmethod
    def validate_library_path(cls, v):
        path = Path(v)
        if not path.is_absolute() and not str(v).startswith(('.', '~')):
            raise ValueError('Library path must be absolute or relative')
        return str(path.expanduser().resolve())


class SelectLibraryRequest(BaseModel):
    """Schema for selecting a library"""
    library_name: str = Field(..., min_length=1)


# ========== Download Operations ==========

class DownloadBooksRequest(BaseModel):
    """Schema for download books request"""
    selected_asins: List[str] = Field(..., min_items=1, description="List of ASINs to download")
    library_name: str = Field(..., min_length=1, description="Target library name")
    cleanup_aax: bool = Field(default=True, description="Remove AAX files after conversion")
    
    @field_validator('selected_asins')
    @classmethod
    def validate_asins(cls, v):
        if not v:
            raise ValueError('At least one ASIN must be provided')
        # Basic ASIN format validation (10 characters, alphanumeric)
        for asin in v:
            if not asin or len(asin) != 10:
                raise ValueError(f'Invalid ASIN format: {asin}')
            if not asin.isalnum():
                raise ValueError(f'ASIN must be alphanumeric: {asin}')
        return v


class SyncLibraryRequest(BaseModel):
    """Schema for library sync request"""
    library_name: str = Field(..., min_length=1)


# ========== Import Operations ==========

class ScanDirectoryRequest(BaseModel):
    """Schema for scanning a directory for M4B files"""
    source_directory: str = Field(..., min_length=1, description="Directory to scan")
    
    @field_validator('source_directory')
    @classmethod
    def validate_source_directory(cls, v):
        path = Path(v).expanduser().resolve()
        if not path.exists():
            raise ValueError(f'Directory does not exist: {v}')
        if not path.is_dir():
            raise ValueError(f'Path is not a directory: {v}')
        return str(path)


class MatchImportsRequest(BaseModel):
    """Schema for matching imports with Audible metadata"""
    source_directory: str = Field(..., min_length=1)
    account_name: str = Field(..., min_length=1)


class ImportBooksRequest(BaseModel):
    """Schema for importing matched books"""
    imports: List[Dict[str, Any]] = Field(..., min_items=1, description="List of import items")
    library_name: str = Field(..., min_length=1)
    account_name: str = Field(..., min_length=1)
    
    @field_validator('imports')
    @classmethod
    def validate_imports(cls, v):
        if not v:
            raise ValueError('At least one import must be provided')
        for item in v:
            if 'file_path' not in item:
                raise ValueError('Each import must have a file_path')
            if 'audible_product' not in item:
                raise ValueError('Each import must have audible_product metadata')
        return v


# ========== Authentication ==========

class AuthenticateAccountRequest(BaseModel):
    """Schema for account authentication"""
    account_name: str = Field(..., min_length=1)


class FetchLibraryRequest(BaseModel):
    """Schema for fetching Audible library"""
    account_name: str = Field(..., min_length=1)


class CheckAuthRequest(BaseModel):
    """Schema for checking authentication status"""
    account_name: str = Field(..., min_length=1)


# ========== Settings ==========

class UpdateNamingPatternRequest(BaseModel):
    """Schema for updating naming pattern"""
    pattern: str = Field(..., min_length=1, max_length=500)
    preset: Optional[str] = Field(default=None, max_length=50)
    
    @field_validator('pattern')
    @classmethod
    def validate_pattern(cls, v):
        # Basic validation - check for valid placeholders
        valid_placeholders = [
            '{author}', '{title}', '{series}', '{series_sequence}', 
            '{narrator}', '{year}', '{asin}', '{subtitle}', '{publisher}'
        ]
        # Check if pattern contains at least one valid placeholder
        has_placeholder = any(placeholder in v for placeholder in valid_placeholders)
        if not has_placeholder:
            raise ValueError(f'Pattern must contain at least one valid placeholder: {", ".join(valid_placeholders)}')
        return v


class SetInvitationTokenRequest(BaseModel):
    """Schema for setting custom invitation token"""
    token: str = Field(..., min_length=8, max_length=100, pattern="^[a-zA-Z0-9_-]+$")


# ========== Helper Functions ==========

def validate_request(schema: type[BaseModel], data: dict) -> BaseModel:
    """
    Validate request data against a Pydantic schema.
    
    Args:
        schema: Pydantic model class to validate against
        data: Dictionary of request data
    
    Returns:
        Validated model instance
    
    Raises:
        ValueError: If validation fails
    """
    try:
        return schema(**data)
    except Exception as e:
        raise ValueError(f"Validation error: {str(e)}")


def get_validation_errors(e: Exception) -> List[Dict[str, Any]]:
    """
    Extract validation errors from Pydantic ValidationError.
    
    Args:
        e: Pydantic ValidationError
    
    Returns:
        List of error dictionaries with field and message
    """
    if hasattr(e, 'errors'):
        return [
            {
                'field': '.'.join(str(loc) for loc in err['loc']),
                'message': err['msg'],
                'type': err['type']
            }
            for err in e.errors()
        ]
    return [{'message': str(e)}]


def validate_json(schema: type[BaseModel]):
    """
    Decorator to validate JSON request data against a Pydantic schema.
    
    Usage:
        @route('/endpoint', methods=['POST'])
        @validate_json(CreateAccountRequest)
        def my_endpoint(validated_data: CreateAccountRequest):
            # validated_data is the Pydantic model instance
            account_name = validated_data.account_name
            ...
    
    Args:
        schema: Pydantic model class to validate against
    
    Returns:
        Decorator function
    """
    def decorator(f: Callable) -> Callable:
        @wraps(f)
        def wrapper(*args, **kwargs):
            try:
                # Get JSON data from request
                data = request.get_json()
                
                if data is None:
                    raise AppValidationError('No JSON data provided')
                
                # Validate against schema
                validated_data = schema(**data)
                
                # Call the original function with validated data
                return f(validated_data, *args, **kwargs)
                
            except ValidationError as e:
                # Pydantic validation error
                errors = get_validation_errors(e)
                error_messages = [f"{err['field']}: {err['message']}" for err in errors]
                raise AppValidationError(
                    '; '.join(error_messages),
                    details={'errors': errors}
                )
            except AppValidationError:
                # Re-raise our custom validation errors
                raise
            except Exception as e:
                # Unexpected error
                raise AppValidationError(f'Validation failed: {str(e)}')
        
        return wrapper
    return decorator


def validate_query_params(schema: type[BaseModel]):
    """
    Decorator to validate query parameters against a Pydantic schema.
    
    Usage:
        @route('/endpoint', methods=['GET'])
        @validate_query_params(SearchQuerySchema)
        def my_endpoint(validated_params: SearchQuerySchema):
            # validated_params is the Pydantic model instance
            query = validated_params.q
            ...
    
    Args:
        schema: Pydantic model class to validate against
    
    Returns:
        Decorator function
    """
    def decorator(f: Callable) -> Callable:
        @wraps(f)
        def wrapper(*args, **kwargs):
            try:
                # Get query parameters from request
                data = request.args.to_dict()
                
                # Validate against schema
                validated_data = schema(**data)
                
                # Call the original function with validated data
                return f(validated_data, *args, **kwargs)
                
            except ValidationError as e:
                # Pydantic validation error
                errors = get_validation_errors(e)
                error_messages = [f"{err['field']}: {err['message']}" for err in errors]
                raise AppValidationError(
                    '; '.join(error_messages),
                    details={'errors': errors}
                )
            except AppValidationError:
                # Re-raise our custom validation errors
                raise
            except Exception as e:
                # Unexpected error
                raise AppValidationError(f'Validation failed: {str(e)}')
        
        return wrapper
    return decorator

