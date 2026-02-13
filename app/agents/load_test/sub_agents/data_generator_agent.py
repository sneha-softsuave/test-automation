"""DataGeneratorAgent: Generates realistic test data for load testing."""

import json
import re
import logging
from typing import List, Dict, Any
from faker import Faker

from app.agents.load_test.sub_agents.base_load_test_agent import BaseLoadTestAgent
from app.agents.load_test.state import AgenticLoadTestState

# Configure logger
logger = logging.getLogger(__name__)


class DataGeneratorAgent(BaseLoadTestAgent):
    """
    Generates realistic test data based on API analysis.

    Responsibilities:
    - Generate realistic usernames, emails, passwords
    - Create product IDs, SKUs, prices for e-commerce
    - Generate addresses, phone numbers, names
    - Ensure data diversity (no duplicates for unique fields)
    - Use Faker for common fields, AI for domain-specific data
    """

    def __init__(self, *args, **kwargs):
        """Initialize agent with Faker library."""
        super().__init__(*args, **kwargs)
        self.faker = Faker()

    def execute(self, state: AgenticLoadTestState) -> AgenticLoadTestState:
        """
        Generate test data based on required fields and API type.

        Args:
            state: Current state with required_fields and api_type

        Returns:
            Updated state with generated_data
        """
        logger.info("\n" + "="*80)
        logger.info("🤖 AGENT 2/6: DataGeneratorAgent")
        logger.info("="*80)

        required_fields = state.get('required_fields', [])
        api_type = state.get('api_type', 'crud_read')
        recommended_users = state.get('recommended_users', 100)
        validated_suggestions = state.get('validated_suggestions')  # NEW

        logger.info("📋 Input:")
        logger.info(f"   • Required Fields: {required_fields}")
        logger.info(f"   • API Type: {api_type}")
        logger.info(f"   • Recommended Users: {recommended_users}")

        # NEW: Log if using custom suggestions
        logger.info(f"\n🔍 DEBUG: validated_suggestions = {validated_suggestions}")
        if validated_suggestions:
            logger.info(f"\n📝 Using Custom Suggestions for Data Generation")
            logger.info(f"   {validated_suggestions[:150]}...")
        else:
            logger.info(f"\n⚠️  No validated suggestions found in state!")

        if not required_fields:
            logger.info("\nℹ️  No test data fields required (static payload)")
            self.add_thought(
                state,
                "No test data fields required",
                "API uses static payload, skipping data generation",
                "generating_data"
            )
            state['generated_data'] = []
            state['data_generation_method'] = 'none'
            logger.info("✅ DataGeneratorAgent Complete!")
            logger.info("="*80 + "\n")
            return state

        self.add_thought(
            state,
            f"Generating test data for {len(required_fields)} fields",
            f"Creating {min(recommended_users, 100)} unique data entries using hybrid approach",
            "generating_data"
        )

        # Determine generation method based on fields
        logger.info("\n🔍 Step 1: Determining Generation Method...")
        generation_method = self._determine_generation_method(required_fields)
        logger.info(f"   ✅ Selected: {generation_method}")

        self.add_thought(
            state,
            f"Using {generation_method} generation method",
            f"Best approach for fields: {', '.join(required_fields)}",
            "generating_data"
        )

        # Generate data
        logger.info(f"\n🎲 Step 2: Generating Test Data...")
        count = min(recommended_users, 100)  # Cap at 100 for performance
        if generation_method == 'faker':
            generated_data = self._generate_with_faker(required_fields, count, api_type)
        elif generation_method == 'ai':
            generated_data = self._generate_with_ai(required_fields, count, api_type, validated_suggestions)  # NEW
        else:  # hybrid
            generated_data = self._generate_hybrid(required_fields, count, api_type, validated_suggestions)  # NEW

        logger.info(f"   ✅ Generated {len(generated_data)} test data entries")

        # Show sample credentials in terminal
        logger.info("\n📊 Sample Generated Credentials (showing first 5):")
        for i, entry in enumerate(generated_data[:5], 1):
            logger.info(f"   Entry {i}:")
            for key, value in entry.items():
                # Mask passwords for security
                display_value = value if 'password' not in key.lower() else '*' * 8
                logger.info(f"      • {key}: {display_value}")

        if len(generated_data) > 5:
            logger.info(f"   ... and {len(generated_data) - 5} more entries")

        self.add_thought(
            state,
            f"Generated {len(generated_data)} test data entries",
            f"Each entry contains: {', '.join(required_fields)}",
            "generating_data"
        )

        state['generated_data'] = generated_data
        state['data_generation_method'] = generation_method

        logger.info("\n✅ DataGeneratorAgent Complete!")
        logger.info("="*80 + "\n")

        return state

    def _determine_generation_method(self, required_fields: List[str]) -> str:
        """
        Determine best generation method based on field types.

        Returns:
            'faker', 'ai', or 'hybrid'
        """
        faker_fields = {
            'username', 'email', 'name', 'firstname', 'lastname', 'first_name', 'last_name',
            'phone', 'phone_number', 'address', 'city', 'state', 'zipcode', 'zip',
            'country', 'company', 'job', 'url', 'domain', 'ip', 'date', 'time'
        }

        domain_specific_fields = {
            'product_id', 'sku', 'product_name', 'category', 'price', 'quantity',
            'order_id', 'transaction_id', 'payment_method', 'card_number',
            'description', 'title', 'content', 'tags', 'rating'
        }

        # Check which fields are Faker-compatible
        faker_count = sum(1 for field in required_fields if any(f in field.lower() for f in faker_fields))
        domain_count = sum(1 for field in required_fields if any(f in field.lower() for f in domain_specific_fields))

        if faker_count == len(required_fields):
            return 'faker'
        elif domain_count > 0:
            return 'hybrid'
        else:
            return 'ai'

    def _generate_with_faker(
        self,
        required_fields: List[str],
        count: int,
        api_type: str
    ) -> List[Dict[str, Any]]:
        """Generate test data using Faker library."""
        data = []

        for i in range(count):
            entry = {}
            for field in required_fields:
                field_lower = field.lower()

                if 'username' in field_lower or 'user' in field_lower:
                    entry[field] = self.faker.user_name() + str(i)
                elif 'email' in field_lower:
                    entry[field] = self.faker.email()
                elif 'password' in field_lower or 'pass' in field_lower:
                    entry[field] = self.faker.password(length=12)
                elif 'phone' in field_lower:
                    entry[field] = self.faker.phone_number()
                elif 'address' in field_lower:
                    entry[field] = self.faker.address().replace('\n', ', ')
                elif 'city' in field_lower:
                    entry[field] = self.faker.city()
                elif 'state' in field_lower:
                    entry[field] = self.faker.state()
                elif 'zip' in field_lower:
                    entry[field] = self.faker.zipcode()
                elif 'country' in field_lower:
                    entry[field] = self.faker.country()
                elif 'firstname' in field_lower or 'first_name' in field_lower:
                    entry[field] = self.faker.first_name()
                elif 'lastname' in field_lower or 'last_name' in field_lower:
                    entry[field] = self.faker.last_name()
                elif 'name' in field_lower:
                    entry[field] = self.faker.name()
                elif 'company' in field_lower:
                    entry[field] = self.faker.company()
                elif 'url' in field_lower:
                    entry[field] = self.faker.url()
                else:
                    # Default: generate text
                    entry[field] = self.faker.word() + str(i)

            data.append(entry)

        return data

    def _generate_with_ai(
        self,
        required_fields: List[str],
        count: int,
        api_type: str,
        validated_suggestions: str = None
    ) -> List[Dict[str, Any]]:
        """Generate test data using AI."""
        logger.info(f"\n🔍 DEBUG _generate_with_ai: validated_suggestions = {validated_suggestions}")

        # NEW: Add suggestions section if provided
        suggestions_section = ""
        constraint_reminder = ""
        email_domain_override = ""

        if validated_suggestions:
            # Check if email domain is specified
            suggestions_lower = str(validated_suggestions).lower()
            if '@' in suggestions_lower and 'email' in required_fields:
                # Extract the domain
                import re
                domain_match = re.search(r'@([\w\.-]+\.[\w]+)', str(validated_suggestions))
                if domain_match:
                    domain = domain_match.group(0)  # includes @
                    email_domain_override = f"""

**EMAIL DOMAIN REQUIREMENT:**
ALL email addresses MUST use the domain: {domain}
DO NOT use @example.com, @example.org, @gmail.com, or any other domain.
ONLY use: {domain}

Example correct emails:
- user1{domain}
- john.doe{domain}
- test123{domain}

Example WRONG emails (DO NOT USE):
- user@example.com ❌
- user@example.org ❌
- user@gmail.com ❌
"""

            suggestions_section = f"""

**CRITICAL USER CONSTRAINTS - YOU MUST FOLLOW THESE EXACTLY:**
{validated_suggestions}
{email_domain_override}

IMPORTANT: The user has specified custom rules above. You MUST follow them.
For example:
- If user specifies email domain → ALL emails must use ONLY that domain
- If user specifies value ranges → ALL values must be within those ranges
- If user specifies formats → ALL data must match those formats
"""
            # Add reminder in requirements section too
            suggestions_str = str(validated_suggestions)
            constraint_reminder = f"\n- **CRITICAL:** Follow the user's custom constraints above: {suggestions_str[:100]}..."

        prompt = f"""Generate realistic test data for load testing.

API Type: {api_type}
Required Fields: {required_fields}
Count: {count} entries
{suggestions_section}

Requirements:
- All field values must be realistic for the API type
- Ensure diversity (no duplicate values for unique fields like usernames/emails)
- Format as JSON array
- Keep values concise and realistic{constraint_reminder}

Return ONLY a JSON array (no markdown, no explanations):
[
  {{{', '.join(f'"{field}": "<value>"' for field in required_fields)}}},
  ...
]"""

        try:
            response = self.call_llm(prompt)

            # Extract JSON array from response
            json_match = re.search(r'\[.*\]', response, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group(0))

                # Ensure we have enough entries
                if len(data) >= count * 0.8:  # Accept if we got at least 80%
                    return data[:count]
        except Exception as e:
            print(f"AI generation failed: {e}")

        # Fallback to Faker if AI fails
        return self._generate_with_faker(required_fields, count, api_type)

    def _generate_hybrid(
        self,
        required_fields: List[str],
        count: int,
        api_type: str,
        validated_suggestions: str = None
    ) -> List[Dict[str, Any]]:
        """
        Generate test data using hybrid approach (Faker + AI).

        Faker for common fields, AI for domain-specific fields.
        """
        data = []

        # Separate fields into Faker-compatible and domain-specific
        faker_fields = []
        domain_fields = []

        faker_keywords = {
            'username', 'email', 'password', 'name', 'firstname', 'lastname',
            'phone', 'address', 'city', 'state', 'zip', 'country'
        }

        for field in required_fields:
            if any(keyword in field.lower() for keyword in faker_keywords):
                faker_fields.append(field)
            else:
                domain_fields.append(field)

        # Generate Faker data first
        for i in range(count):
            entry = {}

            # Faker fields
            for field in faker_fields:
                field_lower = field.lower()

                if 'username' in field_lower:
                    entry[field] = f"{self.faker.user_name()}{i}"
                elif 'email' in field_lower:
                    entry[field] = self.faker.email()
                elif 'password' in field_lower:
                    entry[field] = self.faker.password(length=12)
                elif 'phone' in field_lower:
                    entry[field] = self.faker.phone_number()
                elif 'address' in field_lower:
                    entry[field] = self.faker.address().replace('\n', ', ')
                elif 'name' in field_lower:
                    entry[field] = self.faker.name()

            data.append(entry)

        # Generate domain-specific fields with AI if needed
        if domain_fields:
            domain_data = self._generate_domain_specific_fields(domain_fields, count, api_type, validated_suggestions)  # NEW

            # Merge domain data into Faker data
            for i, domain_entry in enumerate(domain_data):
                if i < len(data):
                    data[i].update(domain_entry)

        return data

    def _generate_domain_specific_fields(
        self,
        fields: List[str],
        count: int,
        api_type: str,
        validated_suggestions: str = None
    ) -> List[Dict[str, Any]]:
        """Generate domain-specific fields using AI or templates."""
        # For e-commerce fields, use templates
        if api_type in ['transaction', 'search'] and any('product' in f.lower() for f in fields):
            return self._generate_ecommerce_fields(fields, count)

        # NEW: Add suggestions section
        suggestions_section = ""
        if validated_suggestions:
            suggestions_section = f"\n\nUser Suggestions: {validated_suggestions}"

        # For other domain fields, use AI
        prompt = f"""Generate realistic values for these fields for {api_type} API:

Fields: {fields}
Count: {count} entries
{suggestions_section}

Return ONLY a JSON array with these fields:
[
  {{{', '.join(f'"{field}": "<realistic_value>"' for field in fields)}}},
  ...
]"""

        try:
            response = self.call_llm(prompt)
            json_match = re.search(r'\[.*\]', response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group(0))[:count]
        except Exception as e:
            print(f"Domain field generation failed: {e}")

        # Fallback to simple templates
        return [{field: f"value_{i}" for field in fields} for i in range(count)]

    def _generate_ecommerce_fields(self, fields: List[str], count: int) -> List[Dict[str, Any]]:
        """Generate e-commerce specific fields using templates."""
        products = [
            {'product_id': 'P001', 'product_name': 'Laptop', 'category': 'Electronics', 'price': 999.99, 'quantity': 1},
            {'product_id': 'P002', 'product_name': 'Smartphone', 'category': 'Electronics', 'price': 699.99, 'quantity': 2},
            {'product_id': 'P003', 'product_name': 'Headphones', 'category': 'Audio', 'price': 149.99, 'quantity': 1},
            {'product_id': 'P004', 'product_name': 'Keyboard', 'category': 'Accessories', 'price': 79.99, 'quantity': 1},
            {'product_id': 'P005', 'product_name': 'Monitor', 'category': 'Electronics', 'price': 299.99, 'quantity': 1},
        ]

        data = []
        for i in range(count):
            product = products[i % len(products)].copy()
            # Filter to only include requested fields
            entry = {field: product.get(field, f"value_{i}") for field in fields}
            data.append(entry)

        return data
