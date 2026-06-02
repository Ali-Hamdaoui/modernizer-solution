package com.example.contracts.api;

import java.util.List;
import javax.persistence.Entity;
import javax.xml.bind.annotation.XmlRootElement;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;

@RequestMapping("/customers")
public interface CustomerContract {
    @GetMapping
    List<CustomerDto> listCustomers();

    @XmlRootElement
    @Entity
    class CustomerDto {
        private String id;
        private String displayName;

        public String getId() {
            return id;
        }

        public void setId(String id) {
            this.id = id;
        }

        public String getDisplayName() {
            return displayName;
        }

        public void setDisplayName(String displayName) {
            this.displayName = displayName;
        }
    }
}
