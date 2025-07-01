import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Union
import re
import json
from pathlib import Path

@dataclass
class SVGToken:
    """Represents a tokenized element from an SVG group"""
    type: str  # "label", "image", "other"
    content: str
    element: Optional[ET.Element] = None
    position: int = 0
    original_content: str = field(default="")
    
    def __post_init__(self):
        if not self.original_content:
            self.original_content = self.content

@dataclass
class GroupMatch:
    """Represents a matched SVG group with its tokens"""
    element: ET.Element
    tokens: List[SVGToken]
    position: int
    group_id: str = ""
    
    def get_tokens_by_type(self, token_type: str) -> List[SVGToken]:
        """Get all tokens of a specific type"""
        return [token for token in self.tokens if token.type == token_type]
    
    def get_label_tokens(self) -> List[SVGToken]:
        """Get all label tokens"""
        return self.get_tokens_by_type("label")
    
    def get_image_tokens(self) -> List[SVGToken]:
        """Get all image tokens"""
        return self.get_tokens_by_type("image")

class SVGTokenizer:
    """Main SVG tokenizer class for parsing and modifying SVG files"""
    
    def __init__(self, svg_path: Union[str, Path]):
        self.svg_path = Path(svg_path)
        self.tree: Optional[ET.ElementTree] = None
        self.root: Optional[ET.Element] = None
        self.matched_groups: List[GroupMatch] = []
        self.namespaces = {
            'svg': 'http://www.w3.org/2000/svg',
            'xlink': 'http://www.w3.org/1999/xlink'
        }
        self._register_namespaces()
    
    def _register_namespaces(self):
        """Register XML namespaces to avoid ns0: prefixes"""
        for prefix, uri in self.namespaces.items():
            ET.register_namespace(prefix, uri)
    
    def parse_and_tokenize(self) -> 'SVGTokenizer':
        """Parse SVG file and tokenize eligible groups"""
        if not self.svg_path.exists():
            raise FileNotFoundError(f"SVG file not found: {self.svg_path}")
        
        try:
            self.tree = ET.parse(self.svg_path)
            self.root = self.tree.getroot()
        except ET.ParseError as e:
            raise ValueError(f"Invalid SVG file: {e}")
        
        # Clear previous results
        self.matched_groups.clear()
        
        # Find and process eligible groups
        eligible_groups = self._find_eligible_groups()
        
        for i, group in enumerate(eligible_groups):
            tokens = self._tokenize_group(group)
            group_match = GroupMatch(
                element=group,
                tokens=tokens,
                position=i,
                group_id=f"group_{i:03d}"
            )
            self.matched_groups.append(group_match)
        
        return self
    
    def _find_eligible_groups(self) -> List[ET.Element]:
        """Find groups that meet the eligibility criteria"""
        eligible_groups = []
        
        def is_eligible_group(group: ET.Element) -> bool:
            """Check if a group meets the eligibility criteria"""
            # Rule 1: Group must NOT contain child groups
            for child in group:
                if self._is_group_element(child):
                    return False
            
            # Rule 2: Must have direct <text> and <image> children
            has_eligible_text = False
            has_image = False
            
            for child in group:
                if self._is_text_element(child):
                    text_content = self._extract_text_content(child)
                    if self._contains_target_identifier(text_content):
                        has_eligible_text = True
                elif self._is_image_element(child):
                    has_image = True
            
            return has_eligible_text and has_image
        
        def traverse_groups(element: ET.Element):
            """Recursively traverse and collect eligible groups"""
            for child in element:
                if self._is_group_element(child):
                    if is_eligible_group(child):
                        eligible_groups.append(child)
                    # Continue traversing even if this group is eligible
                    traverse_groups(child)
        
        if self.root is not None:
            traverse_groups(self.root)
        
        return eligible_groups
    
    def _tokenize_group(self, group: ET.Element) -> List[SVGToken]:
        """Convert group elements into tokens"""
        tokens = []
        position = 0
        
        for child in group:
            token = self._create_token_from_element(child, position)
            if token:
                tokens.append(token)
                position += 1
        
        return tokens
    
    def _create_token_from_element(self, element: ET.Element, position: int) -> Optional[SVGToken]:
        """Create a token from an XML element"""
        if self._is_text_element(element):
            text_content = self._extract_text_content(element)
            token_type = "label" if self._contains_target_identifier(text_content) else "other"
            
            return SVGToken(
                type=token_type,
                content=text_content,
                element=element,
                position=position
            )
        
        elif self._is_image_element(element):
            href = self._extract_image_href(element)
            
            return SVGToken(
                type="image",
                content=href,
                element=element,
                position=position
            )
        
        else:
            # Other elements
            content = ET.tostring(element, encoding='unicode')
            
            return SVGToken(
                type="other",
                content=content,
                element=element,
                position=position
            )
    
    def _is_group_element(self, element: ET.Element) -> bool:
        """Check if element is a group"""
        return element.tag.endswith('g')
    
    def _is_text_element(self, element: ET.Element) -> bool:
        """Check if element is a text element"""
        return element.tag.endswith('text')
    
    def _is_image_element(self, element: ET.Element) -> bool:
        """Check if element is an image element"""
        return element.tag.endswith('image')
    
    def _extract_text_content(self, element: ET.Element) -> str:
        """Extract all text content from element including tspan"""
        return ''.join(element.itertext()).strip()
    
    def _extract_image_href(self, element: ET.Element) -> str:
        """Extract href from image element"""
        # Try xlink:href first, then href
        href = element.get('{http://www.w3.org/1999/xlink}href')
        if href is None:
            href = element.get('href', '')
        return href
    
    def _contains_target_identifier(self, text: str) -> bool:
        """Check if text contains the target identifier"""
        return 'txt' in text.lower()
    
    def get_matched_groups(self) -> List[GroupMatch]:
        """Return all matched groups"""
        return self.matched_groups.copy()
    
    def get_group_by_position(self, position: int) -> Optional[GroupMatch]:
        """Get group by its position"""
        for group in self.matched_groups:
            if group.position == position:
                return group
        return None
    
    def get_total_groups(self) -> int:
        """Get total number of matched groups"""
        return len(self.matched_groups)
    
    def get_total_tokens(self) -> int:
        """Get total number of tokens across all groups"""
        return sum(len(group.tokens) for group in self.matched_groups)
    
    def modify_token(self, token: SVGToken, new_content: str) -> bool:
        """Modify a token's content"""
        try:
            if token.type == "label":
                self._modify_text_token(token, new_content)
            elif token.type == "image":
                self._modify_image_token(token, new_content)
            else:
                # For other tokens, update the element directly
                self._modify_other_token(token, new_content)
            
            token.content = new_content
            return True
        
        except Exception as e:
            print(f"Error modifying token: {e}")
            return False
    
    def _modify_text_token(self, token: SVGToken, new_content: str):
        """Modify text token content"""
        if token.element is not None:
            # Check if there are tspan elements within the text element
            text_element = token.element
            tspan_elements = [child for child in token.element if child.tag.endswith('tspan')]
            
            if tspan_elements:
                # Replace content of the first tspan only
                first_tspan = tspan_elements[0]
                first_tspan.clear()
                first_tspan.text = new_content
                # Preserve text element attributes, replacing #008080 with #000000 in style
                for key, value in text_element[0].attrib.items():
                    if key == "style" and "#008080" in value:
                        value = value.replace("#008080", "#000000")
                    text_element[0].set(key, value)
                # Preserve tspan attributes
                for key, value in first_tspan.attrib.items():
                    first_tspan.set(key, value)
            else:
                # Fallback: replace the whole text element content
                # Store original attributes
                original_attribs = dict(token.element.attrib)
                
                # Clear existing content
                token.element.clear()
                token.element.text = new_content
                
                # Restore attributes
                for key, value in original_attribs.items():
                    token.element.set(key, value)
    
    def _modify_image_token(self, token: SVGToken, new_content: str):
        """Modify image token href"""
        if token.element is not None:
            # Update href attribute (prefer xlink:href if it exists)
            if '{http://www.w3.org/1999/xlink}href' in token.element.attrib:
                token.element.set('{http://www.w3.org/1999/xlink}href', new_content)
            else:
                token.element.set('href', new_content)
    
    def _modify_other_token(self, token: SVGToken, new_content: str):
        """Modify other token content"""
        # For other tokens, this is more complex and depends on the specific element
        # For now, we'll just update the content string
        pass
    
    def modify_group_labels(self, group_position: int, new_label: str) -> bool:
        """Modify all label tokens in a specific group"""
        group = self.get_group_by_position(group_position)
        if not group:
            return False
        
        success = True
        for token in group.get_label_tokens():
            if not self.modify_token(token, new_label):
                success = False
        
        return success
    
    def modify_group_images(self, group_position: int, new_image_href: str) -> bool:
        """Modify all image tokens in a specific group"""
        group = self.get_group_by_position(group_position)
        if not group:
            return False
        
        success = True
        for token in group.get_image_tokens():
            if not self.modify_token(token, new_image_href):
                success = False
        
        return success
    
    def save_svg(self, output_path: Union[str, Path]) -> bool:
        """Save the modified SVG to file"""
        try:
            output_path = Path(output_path)
            
            if self.tree is not None:
                self.tree.write(
                    str(output_path),
                    encoding='utf-8',
                    xml_declaration=False
                )
                return True
            return False
        
        except Exception as e:
            print(f"Error saving SVG: {e}")
            return False
    
    def export_structure(self, output_path: Union[str, Path] = None) -> Dict[str, Any]:
        """Export interoperable structure as JSON"""
        structure = self.get_interoperable_structure()
        
        if output_path:
            output_path = Path(output_path)
            try:
                with open(output_path, 'w', encoding='utf-8') as f:
                    json.dump(structure, f, indent=2, ensure_ascii=False)
            except Exception as e:
                print(f"Error exporting structure: {e}")
        
        return structure
    
    def get_interoperable_structure(self) -> Dict[str, Any]:
        """Return JSON-serializable structure for external use"""
        return {
            'metadata': {
                'source_file': str(self.svg_path),
                'total_groups': self.get_total_groups(),
                'total_tokens': self.get_total_tokens(),
                'tokens_by_type': self._get_token_type_counts()
            },
            'groups': [self._serialize_group(group) for group in self.matched_groups],
            'tokens_by_type': self._get_tokens_by_type()
        }
    
    def _get_token_type_counts(self) -> Dict[str, int]:
        """Get count of tokens by type"""
        counts = {'label': 0, 'image': 0, 'other': 0}
        for group in self.matched_groups:
            for token in group.tokens:
                counts[token.type] = counts.get(token.type, 0) + 1
        return counts
    
    def _get_tokens_by_type(self) -> Dict[str, List[Dict[str, Any]]]:
        """Get all tokens organized by type"""
        tokens_by_type = {'label': [], 'image': [], 'other': []}
        
        for group in self.matched_groups:
            for token in group.tokens:
                token_data = self._serialize_token(token, group.position)
                tokens_by_type[token.type].append(token_data)
        
        return tokens_by_type
    
    def _serialize_group(self, group: GroupMatch) -> Dict[str, Any]:
        """Serialize a group for JSON export"""
        return {
            'group_id': group.group_id,
            'position': group.position,
            'token_count': len(group.tokens),
            'tokens': [self._serialize_token(token, group.position) for token in group.tokens]
        }
    
    def _serialize_token(self, token: SVGToken, group_position: int) -> Dict[str, Any]:
        """Serialize a token for JSON export"""
        return {
            'type': token.type,
            'content': token.content,
            'original_content': token.original_content,
            'position': token.position,
            'group_position': group_position,
            'modified': token.content != token.original_content
        }
    
    def reset_modifications(self):
        """Reset all tokens to their original content"""
        for group in self.matched_groups:
            for token in group.tokens:
                if token.content != token.original_content:
                    self.modify_token(token, token.original_content)
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get processing statistics"""
        return {
            'total_groups': self.get_total_groups(),
            'total_tokens': self.get_total_tokens(),
            'tokens_by_type': self._get_token_type_counts(),
            'modified_tokens': sum(
                1 for group in self.matched_groups
                for token in group.tokens
                if token.content != token.original_content
            )
        }

# Convenience functions for simple usage
def process_svg_file(input_path: Union[str, Path], output_path: Union[str, Path] = None) -> SVGTokenizer:
    """Process SVG file and return tokenizer instance"""
    tokenizer = SVGTokenizer(input_path)
    tokenizer.parse_and_tokenize()
    
    if output_path:
        tokenizer.save_svg(output_path)
    
    return tokenizer

def quick_modify_svg(input_path: Union[str, Path], output_path: Union[str, Path], 
                    label_template: str = "Card {index:02d}", 
                    image_href: str = "") -> bool:
    """Quick modification of SVG with standard patterns"""
    try:
        tokenizer = process_svg_file(input_path)
        
        for i, group in enumerate(tokenizer.get_matched_groups(), 1):
            # Modify labels
            new_label = label_template.format(index=i)
            tokenizer.modify_group_labels(group.position, new_label)
            
            # Modify images if href provided
            if image_href:
                tokenizer.modify_group_images(group.position, image_href)
        
        return tokenizer.save_svg(output_path)
    
    except Exception as e:
        print(f"Error in quick modify: {e}")
        return False

